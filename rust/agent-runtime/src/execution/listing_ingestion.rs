//! Observed Naukri listing persistence. Identity is source/URL evidence, never title similarity.
use super::{filters, storage::*};
use crate::{Failure, Result, context_contract::python_space};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
fn conflict() -> Failure {
    Failure("job_identity_requires_review")
}
fn collapse(value: &str) -> String {
    folded(value)
        .split(python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
/// Input must already pass the actual native observed-job contract, including bounds.
pub fn normalized(work: &Value, observed: &Value, now: DateTime<Utc>) -> Result<Value> {
    let url = filters::naukri_url(work["url"].as_str().ok_or_else(invalid)?)?;
    if observed["requisition"] != work["requisition"]
        || url.rsplit('-').next() != work["requisition"].as_str()
    {
        return Err(Failure("queue_requisition_changed"));
    }
    let posted = if observed["posted_at"].is_null() {
        Value::Null
    } else {
        let at = timestamp(&observed["posted_at"])?;
        if at.year() < 1990 || at > now + chrono::Duration::days(1) {
            return Err(conflict());
        }
        json!(stamp(at))
    };
    use chrono::Datelike;
    let number = |key: &str| observed[key].as_f64().map_or(Value::Null, |v| json!(v));
    Ok(
        json!({"source_name":"naukri","source_job_id":work["requisition"],"original_url":url,"canonical_url":url,"application_url":null,"company_name":observed["company"],"company_domain":null,"title":observed["title"],"description":observed["description"],"location":observed["location"],"country":null,"region":null,"is_remote":match observed["remote_type"].as_str(){Some("remote")=>json!(true),Some("onsite")=>json!(false),_=>Value::Null},"remote_type":observed["remote_type"],"employment_type":observed["employment_type"],"experience_level":null,"experience_min_years":number("experience_min"),"experience_max_years":number("experience_max"),"salary_raw":null,"salary_min":number("salary_min"),"salary_max":number("salary_max"),"salary_currency":observed["salary_currency"],"salary_period":observed["salary_period"],"equity":null,"skills_required":observed["skills"],"skills_preferred":[],"date_posted":posted,"first_observed_date":stamp(now),"last_observed_date":stamp(now),"retrieved_at":stamp(now),"data_provenance":{"method":"bound_browser_ui","evidence_sha256":observed["evidence_sha256"],"observed_at":stamp(now),"posting_recruiter":observed["posting_recruiter"],"experience_requirement":"required","observed_posted_date":observed["posted_date"]},"company_intelligence":{},"source_verification_status":"observed","quality_flags":[],"is_confirmed_current":false}),
    )
}
fn amount(number: f64) -> String {
    let raw = format!("{number:.0}");
    let mut out = String::new();
    for (i, c) in raw.chars().enumerate() {
        if i > 0 && (raw.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}
fn salary(item: &Value) -> Option<String> {
    let lo = item["salary_min"].as_f64();
    let hi = item["salary_max"].as_f64();
    if lo.is_none() && hi.is_none() {
        return None;
    }
    let currency = item["salary_currency"].as_str().unwrap_or("");
    let value = match (lo, hi) {
        (Some(lo), Some(hi)) => format!("{currency}{} - {currency}{}", amount(lo), amount(hi)),
        _ => format!("{currency}{}", lo.or(hi).unwrap()),
    };
    Some(value.chars().take(100).collect())
}
async fn company_in(tx: &mut Transaction<'_, Postgres>, name: &str) -> Result<Uuid> {
    let names: Vec<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(c) FROM companies c WHERE lower(name)=lower($1) ORDER BY id LIMIT 2",
    )
    .bind(name)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let ambiguous = names.len() > 1;
    let candidate = if ambiguous {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c WHERE lower(name)=lower($1) AND domain IS NULL ORDER BY id LIMIT 2").bind(name).fetch_all(&mut **tx).await.map_err(db)?;
        if rows.len() == 1 {
            rows.into_iter().next()
        } else {
            None
        }
    } else {
        names.into_iter().next()
    };
    if let Some(candidate) = candidate {
        return candidate["id"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .ok_or_else(invalid);
    }
    let id = Uuid::new_v4();
    let metadata = if ambiguous {
        json!({"identity_review_required":true,"identity_resolution":"ambiguous_name_without_domain"})
    } else {
        json!({})
    };
    let ack: Option<Uuid> = sqlx::query_scalar(
        "INSERT INTO companies(id,name,is_catch_all,metadata) VALUES($1,$2,false,$3) RETURNING id",
    )
    .bind(id)
    .bind(name)
    .bind(metadata)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if ack != Some(id) {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok(id)
}
fn legacy_url_matches(raw: &str, expected: &str) -> bool {
    let Some(safe) = crate::resources::public_https(raw) else {
        return false;
    };
    let Ok(parsed) = reqwest::Url::parse(&safe) else {
        return false;
    };
    if parsed.host_str() != Some("www.naukri.com") {
        return false;
    }
    if parsed.query_pairs().any(|(k, _)| {
        let k = k.to_lowercase();
        !k.starts_with("utm_")
            && ![
                "fbclid",
                "gclid",
                "ref",
                "referrer",
                "source",
                "trk",
                "trackingid",
                "gh_src",
            ]
            .contains(&k.as_str())
    }) {
        return false;
    }
    filters::naukri_url(raw).is_ok_and(|url| url == expected)
}
async fn existing_in(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    identity: &str,
    owner: bool,
) -> Result<Option<Value>> {
    let observed: Option<Uuid> = sqlx::query_scalar(
        "SELECT job_id FROM job_source_observations WHERE source='naukri' AND identity_key=$1",
    )
    .bind(identity)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if let Some(id) = observed {
        return sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1 FOR UPDATE")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or_else(conflict)
            .map(Some);
    }
    let url = item["canonical_url"].as_str().ok_or_else(invalid)?;
    let exact:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE canonical_key=$1 OR job_url=$1 ORDER BY id LIMIT 2 FOR UPDATE").bind(url).fetch_all(&mut **tx).await.map_err(db)?;
    if exact.len() > 1 {
        return Err(conflict());
    }
    if !exact.is_empty() {
        return Ok(exact.into_iter().next());
    }
    if owner && filters::naukri_url(url).is_err() {
        let legacy:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE canonical_key IS NULL ORDER BY id LIMIT 10001 FOR UPDATE").fetch_all(&mut **tx).await.map_err(db)?;
        if legacy.len() > 10000 {
            return Err(Failure("execution_active_inventory_limit"));
        }
        let matching = legacy
            .into_iter()
            .filter(|j| {
                j["job_url"]
                    .as_str()
                    .and_then(|raw| crate::job_urls::canonical(raw).ok())
                    .is_some_and(|u| u == url)
            })
            .collect::<Vec<_>>();
        if matching.len() > 1 {
            return Err(conflict());
        }
        return Ok(matching.into_iter().next());
    }
    let req = item["source_job_id"].as_str().ok_or_else(invalid)?;
    let legacy:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE canonical_key IS NULL AND job_url ~ $1 ORDER BY id LIMIT 10001 FOR UPDATE").bind(format!("-{req}/?([?#].*)?$" )).fetch_all(&mut **tx).await.map_err(db)?;
    if legacy.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let matched = legacy
        .into_iter()
        .filter(|j| {
            j["job_url"]
                .as_str()
                .filter(|s| legacy_url_matches(s, url))
                .is_some()
        })
        .collect::<Vec<_>>();
    if matched.len() > 1 {
        return Err(conflict());
    }
    Ok(matched.into_iter().next())
}
pub(crate) async fn save_in(tx: &mut Transaction<'_, Postgres>, item: &Value) -> Result<Value> {
    save_mode_in(tx, item, false).await.map(|(value, _)| value)
}
pub(crate) async fn save_owner_in(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
) -> Result<(Value, bool)> {
    save_mode_in(tx, item, true).await
}
async fn save_mode_in(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    owner: bool,
) -> Result<(Value, bool)> {
    // Same bounded identity lock as legacy and public-feed ingestion. Caller holds owner first.
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let identity = format!(
        "{:x}",
        Sha256::digest(format!(
            "id::{}",
            item["source_job_id"].as_str().ok_or_else(invalid)?
        ))
    );
    let existing = existing_in(tx, item, &identity, owner).await?;
    let created = existing.is_none();
    let company = if let Some(existing) = &existing {
        if let Some(id) = existing["company_id"].as_str() {
            let id = id.parse::<Uuid>().map_err(|_| invalid())?;
            let name: Option<String> = sqlx::query_scalar("SELECT name FROM companies WHERE id=$1")
                .bind(id)
                .fetch_optional(&mut **tx)
                .await
                .map_err(db)?;
            if name
                .as_deref()
                .is_none_or(|s| collapse(s) != collapse(item["company_name"].as_str().unwrap()))
            {
                let same_requisition = owner
                    && existing["source_platform"] == "naukri"
                    && matches!(
                        item["data_provenance"]["method"].as_str(),
                        Some("owner_url" | "owner_job_alert")
                    )
                    && existing["job_url"]
                        .as_str()
                        .and_then(|u| filters::naukri_url(u).ok())
                        .is_some_and(|u| u.rsplit('-').next() == item["source_job_id"].as_str());
                if !same_requisition {
                    return Err(conflict());
                }
            }
            id
        } else {
            company_in(tx, item["company_name"].as_str().ok_or_else(invalid)?).await?
        }
    } else {
        company_in(tx, item["company_name"].as_str().ok_or_else(invalid)?).await?
    };
    let id = if let Some(existing) = &existing {
        if existing["source_platform"] != "naukri" && !owner {
            return Err(conflict());
        }
        existing["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?
    } else {
        let id = Uuid::new_v4();
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO jobs(id,company_id,title,job_url,canonical_key,source_platform,status,location,is_remote,remote_type,employment_type,salary_range,skills_required,description,date_posted,first_observed_at,last_observed_at,source_verification_status,salary_min,salary_max,salary_currency,salary_period,discovery_metadata,application_url) SELECT $1,$2,$3->>'title',$3->>'canonical_url',$3->>'canonical_url','naukri','discovered',$3->>'location',coalesce(($3->>'is_remote')::boolean,false),$3->>'remote_type',$3->>'employment_type',$4,ARRAY(SELECT jsonb_array_elements_text($3->'skills_required')),$3->>'description',($3->>'date_posted')::timestamptz,($3->>'first_observed_date')::timestamptz,($3->>'last_observed_date')::timestamptz,$5,($3->>'salary_min')::numeric,($3->>'salary_max')::numeric,$3->>'salary_currency',$3->>'salary_period',$3,$3->>'application_url' RETURNING id").bind(id).bind(company).bind(item).bind(salary(item)).bind(item["source_verification_status"].as_str().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack != Some(id) {
            return Err(Failure("execution_write_ack_failed"));
        }
        id
    };
    if let Some(existing) = existing {
        let primary = existing["source_platform"] == "naukri";
        let salary_empty = [
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
        ]
        .iter()
        .all(|k| existing[*k].is_null());
        let ack:Option<Value>=sqlx::query_scalar("UPDATE jobs SET company_id=coalesce(company_id,$2),canonical_key=coalesce(canonical_key,$3->>'canonical_url'),description=coalesce(nullif(description,''),$3->>'description'),application_url=coalesce(application_url,$3->>'application_url'),employment_type=coalesce(employment_type,$3->>'employment_type'),remote_type=CASE WHEN remote_type IS NULL OR remote_type='unknown' THEN $3->>'remote_type' ELSE remote_type END,is_remote=CASE WHEN remote_type IS NULL OR remote_type='unknown' THEN coalesce(($3->>'is_remote')::boolean,false) ELSE is_remote END,salary_min=CASE WHEN $4 THEN ($3->>'salary_min')::numeric ELSE salary_min END,salary_max=CASE WHEN $4 THEN ($3->>'salary_max')::numeric ELSE salary_max END,salary_currency=CASE WHEN $4 THEN $3->>'salary_currency' ELSE salary_currency END,salary_period=CASE WHEN $4 THEN $3->>'salary_period' ELSE salary_period END,first_observed_at=coalesce(first_observed_at,($3->>'first_observed_date')::timestamptz),last_observed_at=greatest(last_observed_at,($3->>'last_observed_date')::timestamptz),discovery_metadata=CASE WHEN $5 THEN $3 ELSE discovery_metadata END,updated_at=clock_timestamp() WHERE id=$1 RETURNING to_jsonb(jobs)").bind(id).bind(company).bind(item).bind(salary_empty).bind(primary).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack.as_ref().is_none_or(|v| {
            v["id"] != id.to_string()
                || primary && v["discovery_metadata"] != *item
                || [
                    "title",
                    "status",
                    "match_score",
                    "match_explanation",
                    "job_url",
                    "application_url",
                    "company_id",
                ]
                .iter()
                .any(|k| !existing[*k].is_null() && v[*k] != existing[*k])
        }) {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    let mut provenance = item["data_provenance"].clone();
    provenance["deduplication"] = json!("source_or_url_identity");
    provenance["quality_flags"] = item["quality_flags"].clone();
    let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO job_source_observations(id,job_id,source,identity_key,source_job_id,original_url,first_observed_at,last_observed_at,provenance,verification_status) VALUES($1,$2,'naukri',$3,$4,$5,$6::text::timestamptz,$6::text::timestamptz,$7,$8) ON CONFLICT(source,identity_key) DO UPDATE SET last_observed_at=greatest(job_source_observations.last_observed_at,excluded.last_observed_at),provenance=excluded.provenance,verification_status=excluded.verification_status,original_url=excluded.original_url WHERE job_source_observations.job_id=excluded.job_id RETURNING job_id").bind(Uuid::new_v4()).bind(id).bind(identity).bind(item["source_job_id"].as_str().unwrap()).bind(item["original_url"].as_str().unwrap()).bind(item["last_observed_date"].as_str().unwrap()).bind(provenance).bind(item["source_verification_status"].as_str().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack != Some(id) {
        return Err(Failure("execution_write_ack_failed"));
    }
    let saved: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if saved["source_platform"] == "naukri" && saved["discovery_metadata"] != *item
        || saved["company_id"] != company.to_string()
    {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok((saved, created))
}
