//! Exact job identity and fill-only updates preserving the complete saved application row.
use super::sql::{self, Table, db, id, invalid};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;
pub(super) struct Inventory {
    urls: Option<BTreeMap<String, BTreeSet<Uuid>>>,
}
impl Inventory {
    pub(super) fn new() -> Self {
        Self { urls: None }
    }
    async fn legacy(&mut self, tx: &mut Transaction<'_, Postgres>, url: &str) -> Result<Vec<Uuid>> {
        if self.urls.is_none() {
            let rows:Vec<(Uuid,Option<String>)>=sqlx::query_as("SELECT id,CASE WHEN octet_length(job_url)<=8192 THEN job_url ELSE NULL END FROM jobs ORDER BY id LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
            if rows.len() > 10000 || rows.iter().any(|(_, url)| url.is_none()) {
                return Err(Failure("public_job_legacy_identity_inventory_limit"));
            }
            let mut urls: BTreeMap<String, BTreeSet<Uuid>> = BTreeMap::new();
            for (id, url) in rows {
                let raw = url.ok_or_else(invalid)?;
                if raw.chars().count() > 2048 {
                    return Err(Failure("public_job_legacy_identity_inventory_limit"));
                }
                // Malformed legacy URLs are not evidence for a merge and remain untouched.
                if let Ok(key) = canonical(&raw) {
                    urls.entry(key).or_default().insert(id);
                }
            }
            self.urls = Some(urls);
        }
        Ok(self
            .urls
            .as_ref()
            .and_then(|map| map.get(url))
            .map(|ids| ids.iter().copied().collect())
            .unwrap_or_default())
    }
    pub(super) fn remember(&mut self, url: &str, id: Uuid) {
        if let Some(map) = self.urls.as_mut() {
            map.entry(url.to_owned()).or_default().insert(id);
        }
    }
}
fn canonical(raw: &str) -> Result<String> {
    match crate::job_urls::ats(Some(raw))? {
        Some(v) => Ok(v),
        None => crate::job_urls::canonical(raw),
    }
}
pub(super) async fn resolve(
    tx: &mut Transaction<'_, Postgres>,
    inventory: &mut Inventory,
    item: &Value,
) -> Result<(Option<Value>, Option<Value>, &'static str)> {
    let observation = super::super::identity::observation_key(item)?;
    let rows:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM job_source_observations WHERE source=$1 AND identity_key=$2 ORDER BY id LIMIT 2").bind(item["source_name"].as_str()).bind(observation).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(Failure("public_job_source_identity_ambiguous"));
    }
    let prior = if let Some(id) = rows.first() {
        Some(sql::row(tx, Table::Observation, *id).await?)
    } else {
        None
    };
    let url = item["canonical_url"].as_str().ok_or_else(invalid)?;
    let mut ids: Vec<Uuid> = sqlx::query_scalar(
        "SELECT id FROM jobs WHERE canonical_key=$1 OR job_url=$1 ORDER BY id LIMIT 3",
    )
    .bind(url)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    // Complete URL identity is required even if an indexed match exists: a legacy alias may conflict.
    ids.extend(inventory.legacy(tx, url).await?);
    if let Some(prior) = &prior {
        let old_original = canonical(prior["original_url"].as_str().ok_or_else(invalid)?)?;
        let new_original = canonical(item["original_url"].as_str().ok_or_else(invalid)?)?;
        // An ATS identity can be the job's canonical key while the observation retains the portal URL.
        if old_original != url && old_original != new_original {
            return Err(Failure("public_job_source_url_identity_conflict"));
        }
        ids.push(id(&prior["job_id"])?);
    }
    ids.sort();
    ids.dedup();
    if ids.len() > 1 {
        return Err(Failure("public_job_url_identity_ambiguous"));
    }
    let job = if let Some(id) = ids.first() {
        Some(sql::row(tx, Table::Job, *id).await?)
    } else {
        None
    };
    if let Some(job) = &job {
        if !sql::empty(&job["canonical_key"]) && job["canonical_key"] != url {
            return Err(Failure("public_job_source_url_identity_conflict"));
        }
    }
    let reason = if prior.is_some() {
        "source_identity"
    } else if job.is_some() {
        "canonical_url"
    } else {
        "new_job"
    };
    Ok((job, prior, reason))
}
pub(super) async fn content(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    company: Uuid,
) -> Result<Option<Value>> {
    let Some(hash) = super::super::identity::content_identity(item, Some(company))? else {
        return Ok(None);
    };
    let ids: Vec<Uuid> =
        sqlx::query_scalar("SELECT id FROM jobs WHERE content_identity=$1 ORDER BY id LIMIT 2")
            .bind(hash)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    if ids.len() > 1 {
        return Err(Failure("public_job_content_identity_ambiguous"));
    }
    if let Some(id) = ids.first() {
        Ok(Some(sql::row(tx, Table::Job, *id).await?))
    } else {
        Ok(None)
    }
}
fn salary(item: &Value) -> Option<String> {
    if let Some(raw) = item["salary_raw"].as_str().filter(|s| !s.is_empty()) {
        return Some(raw.chars().take(100).collect());
    }
    let currency = item["salary_currency"].as_str().unwrap_or("");
    let number = |v: &Value| {
        v.as_f64().map(|n| {
            let plain = format!("{n:.0}");
            let chars: Vec<char> = plain.chars().collect();
            let mut out = String::new();
            for (i, c) in chars.iter().enumerate() {
                out.push(*c);
                let left = chars.len() - i - 1;
                if left > 0 && left % 3 == 0 && *c != '-' {
                    out.push(',');
                }
            }
            format!("{currency}{out}")
        })
    };
    let value = match (number(&item["salary_min"]), number(&item["salary_max"])) {
        (Some(a), Some(b)) => Some(format!("{a} - {b}")),
        (Some(a), None) | (None, Some(a)) => Some(a),
        _ => None,
    };
    value.map(|v| v.chars().take(100).collect())
}
pub(super) async fn save(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    company: Option<Uuid>,
    before: Option<Value>,
) -> Result<(Value, bool)> {
    let content = super::super::identity::content_identity(item, company)?;
    let stamp = sql::stamp(tx).await?;
    if let Some(before) = before {
        if !before["company_id"].is_null() && before["company_id"] != json!(company) {
            return Err(Failure("public_job_company_identity_conflict"));
        }
        let mut patch = json!({});
        for (field, value) in [
            ("company_id", json!(company)),
            ("canonical_key", item["canonical_url"].clone()),
            ("content_identity", json!(content)),
            ("description", item["description"].clone()),
            ("application_url", item["application_url"].clone()),
            ("employment_type", item["employment_type"].clone()),
            ("first_observed_at", item["first_observed_date"].clone()),
        ] {
            if sql::empty(&before[field]) && !value.is_null() {
                patch[field] = value;
            }
        }
        if [
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
        ]
        .iter()
        .all(|k| before[k].is_null())
        {
            for k in [
                "salary_min",
                "salary_max",
                "salary_currency",
                "salary_period",
            ] {
                patch[k] = item[k].clone();
            }
        }
        if (before["remote_type"].is_null() || before["remote_type"] == "unknown")
            && item["remote_type"] != "unknown"
        {
            patch["remote_type"] = item["remote_type"].clone();
            patch["is_remote"] = json!(item["is_remote"] == true);
        }
        let previous = if before["last_observed_at"].is_null() {
            None
        } else {
            Some(super::super::access::time(&before["last_observed_at"])?)
        };
        let incoming = super::super::access::time(&item["last_observed_date"])?;
        if previous.is_none_or(|v| incoming > v) {
            patch["last_observed_at"] = item["last_observed_date"].clone();
        }
        if !before["discovery_metadata"].is_object() && !before["discovery_metadata"].is_null() {
            return Err(invalid());
        }
        if before["source_platform"] == item["source_name"]
            && before["discovery_metadata"]["original_url"] == item["original_url"]
            && before["discovery_metadata"]["source_job_id"] == item["source_job_id"]
            && previous.is_none_or(|v| incoming >= v)
        {
            let mut metadata = if before["discovery_metadata"].is_null() {
                json!({})
            } else {
                before["discovery_metadata"].clone()
            };
            for k in ["experience_min_years", "experience_max_years"] {
                metadata[k] = item[k].clone();
            }
            patch["discovery_metadata"] = metadata;
        }
        let mut expected = sql::patch(tx, Table::Job, &before, patch).await?;
        if expected == before {
            return Ok((before, false));
        }
        expected["updated_at"] = stamp;
        let saved:Option<Value>=sqlx::query_scalar("UPDATE jobs AS j SET company_id=x.company_id,canonical_key=x.canonical_key,content_identity=x.content_identity,description=x.description,application_url=x.application_url,employment_type=x.employment_type,first_observed_at=x.first_observed_at,last_observed_at=x.last_observed_at,salary_min=x.salary_min,salary_max=x.salary_max,salary_currency=x.salary_currency,salary_period=x.salary_period,remote_type=x.remote_type,is_remote=x.is_remote,discovery_metadata=x.discovery_metadata,updated_at=x.updated_at FROM jsonb_populate_record(NULL::jobs,$2) x WHERE j.id=$1 RETURNING to_jsonb(j)").bind(id(&before["id"])?).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
        return Ok((
            sql::acknowledged(tx, Table::Job, expected, saved, true).await?,
            false,
        ));
    }
    let values = json!({"id":Uuid::new_v4(),"company_id":company,"title":item["title"],"job_url":item["canonical_url"],"source_platform":item["source_name"],"location":item["location"],"is_remote":item["is_remote"]==true,"experience_level":item["experience_level"],"salary_range":salary(item),"skills_required":item["skills_required"],"description":item["description"],"match_score":null,"match_explanation":null,"status":"discovered","date_posted":item["date_posted"],"created_at":stamp,"updated_at":stamp,"canonical_key":item["canonical_url"],"content_identity":content,"application_url":item["application_url"],"remote_type":item["remote_type"],"employment_type":item["employment_type"],"salary_min":item["salary_min"],"salary_max":item["salary_max"],"salary_currency":item["salary_currency"],"salary_period":item["salary_period"],"first_observed_at":item["first_observed_date"],"last_observed_at":item["last_observed_date"],"source_verification_status":item["source_verification_status"],"discovery_metadata":item});
    let expected = sql::typed(tx, Table::Job, &values).await?;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO jobs AS j(id,company_id,title,job_url,source_platform,location,is_remote,experience_level,salary_range,skills_required,description,match_score,match_explanation,status,date_posted,created_at,updated_at,canonical_key,content_identity,application_url,remote_type,employment_type,salary_min,salary_max,salary_currency,salary_period,first_observed_at,last_observed_at,source_verification_status,discovery_metadata) SELECT x.id,x.company_id,x.title,x.job_url,x.source_platform,x.location,x.is_remote,x.experience_level,x.salary_range,x.skills_required,x.description,x.match_score,x.match_explanation,x.status,x.date_posted,x.created_at,x.updated_at,x.canonical_key,x.content_identity,x.application_url,x.remote_type,x.employment_type,x.salary_min,x.salary_max,x.salary_currency,x.salary_period,x.first_observed_at,x.last_observed_at,x.source_verification_status,x.discovery_metadata FROM jsonb_populate_record(NULL::jobs,$1) x RETURNING to_jsonb(j)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    Ok((
        sql::acknowledged(tx, Table::Job, expected, saved, true).await?,
        true,
    ))
}
