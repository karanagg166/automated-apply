//! Saved relevance only. Reviewed prior application history suppresses ranking without changing jobs.
use crate::{Failure, Result, execution::reviewed_history};
use automated_apply_domain::matching::{
    Company, DiscoveryMatch, Listing, Profile, discovery_match,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::BTreeSet;
use uuid::Uuid;
fn invalid() -> Failure {
    Failure("invalid_discovery_run_ranking")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("discovery_run_database_error")
}
fn ids(receipt: &Value) -> Result<Vec<Uuid>> {
    let ids = receipt["job_ids"]
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?
        .iter()
        .map(|v| {
            v.as_str()
                .and_then(|s| s.parse().ok())
                .filter(|v: &Uuid| !v.is_nil())
                .ok_or_else(invalid)
        })
        .collect::<Result<BTreeSet<Uuid>>>()?;
    Ok(ids.into_iter().collect())
}
async fn rows_in(
    tx: &mut Transaction<'_, Postgres>,
    ids: &[Uuid],
) -> Result<Vec<(Value, Option<Value>)>> {
    let rows:Vec<(Option<Value>,Option<Value>,bool)>=sqlx::query_as("SELECT CASE WHEN job_bytes<=1048576 AND sum(job_bytes+company_bytes) OVER()<=33554432 THEN job ELSE NULL END,CASE WHEN has_company AND company_bytes<=1048576 AND sum(job_bytes+company_bytes) OVER()<=33554432 THEN company ELSE NULL END,has_company FROM (SELECT j.id,to_jsonb(j) AS job,CASE WHEN c.id IS NULL THEN NULL ELSE to_jsonb(c) END AS company,octet_length(to_jsonb(j)::text) AS job_bytes,coalesce(octet_length(to_jsonb(c)::text),0) AS company_bytes,c.id IS NOT NULL AS has_company FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE j.id=ANY($1) ORDER BY j.id LIMIT 101) bounded ORDER BY id").bind(ids).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() != ids.len()
        || rows
            .iter()
            .any(|(j, c, has)| j.is_none() || *has && c.is_none())
    {
        return Err(Failure("discovery_run_ranking_inventory_limit"));
    }
    let rows = rows
        .into_iter()
        .map(|(j, c, _)| Ok((j.ok_or_else(invalid)?, c)))
        .collect::<Result<Vec<_>>>()?;
    if rows
        .iter()
        .map(|(j, c)| j.to_string().len() + c.as_ref().map_or(0, |c| c.to_string().len()))
        .sum::<usize>()
        > 32 * 1024 * 1024
    {
        return Err(Failure("discovery_run_ranking_inventory_limit"));
    }
    Ok(rows)
}
pub(super) struct Ranked {
    pub(super) entries: Value,
    pub(super) suppressed: usize,
    pub(super) history_hash: Value,
    ids: Vec<Uuid>,
    rows: Vec<(Value, Option<Value>)>,
    history: Vec<Value>,
    at: DateTime<Utc>,
    enabled: bool,
}
impl Ranked {
    pub(super) async fn verify_in(&self, tx: &mut Transaction<'_, Postgres>) -> Result<()> {
        if self.enabled
            && (rows_in(tx, &self.ids).await? != self.rows
                || reviewed_history::load_in(tx, self.at).await? != self.history)
        {
            return Err(Failure("discovery_run_write_ack_failed"));
        }
        Ok(())
    }
}
pub(super) async fn rank_in(
    tx: &mut Transaction<'_, Postgres>,
    receipt: &Value,
    profile: Option<&Value>,
    now: DateTime<Utc>,
) -> Result<Ranked> {
    let Some(value) = profile else {
        return Ok(Ranked {
            entries: json!([]),
            suppressed: 0,
            history_hash: Value::Null,
            ids: vec![],
            rows: vec![],
            history: vec![],
            at: now,
            enabled: false,
        });
    };
    let profile: Profile = serde_json::from_value(value.clone()).map_err(|_| invalid())?;
    let ids = ids(receipt)?;
    let rows = rows_in(tx, &ids).await?;
    let history = reviewed_history::load_in(tx, now).await?;
    let mut entries = Vec::new();
    let mut suppressed = 0;
    for (job, employer) in &rows {
        if reviewed_history::previously_applied(job, employer.as_ref(), &history) {
            suppressed += 1;
            continue;
        }
        let mut listing = job.clone();
        for (key, fallback) in [
            ("skills_required", json!([])),
            ("remote_type", json!("unknown")),
            ("is_remote", json!(false)),
        ] {
            if listing[key].is_null() {
                listing[key] = fallback;
            }
        }
        let listing: Listing = serde_json::from_value(listing).map_err(|_| invalid())?;
        let company = employer
            .as_ref()
            .map(|v| {
                if !v["metadata"].is_object() && !v["metadata"].is_null() {
                    return Err(invalid());
                }
                Ok(Company {
                    name: v["name"].as_str().ok_or_else(invalid)?.into(),
                    domain: v["domain"].as_str().map(String::from),
                    startup_stage: v["metadata"]["startup_discovery"]["stage"]
                        .as_str()
                        .map(String::from),
                    startup_source: v["metadata"]["startup_discovery"]["source"]
                        .as_str()
                        .map(String::from),
                })
            })
            .transpose()?;
        let mut entry =
            serde_json::to_value(discovery_match(&listing, &profile, company.as_ref(), false))
                .map_err(|_| invalid())?;
        entry["job_id"] = job["id"].clone();
        entry["profile_version"] = value["version"].clone();
        entries.push(entry);
    }
    entries.sort_by(|a, b| {
        b["match_score"]
            .as_f64()
            .unwrap_or(0.0)
            .total_cmp(&a["match_score"].as_f64().unwrap_or(0.0))
            .then_with(|| a["job_id"].as_str().cmp(&b["job_id"].as_str()))
    });
    let entries = project(&json!(entries), receipt, &value["version"])?;
    Ok(Ranked {
        entries,
        suppressed,
        history_hash: json!(crate::python_json::digest(&json!(history))),
        ids,
        rows,
        history,
        at: now,
        enabled: true,
    })
}
/// Rehydrate only the actual score DTO and original IDs/version; arbitrary journal fields are omitted.
pub(super) fn project(value: &Value, receipt: &Value, version: &Value) -> Result<Value> {
    let ids = ids(receipt)?;
    let mut seen = BTreeSet::new();
    let mut projected = Vec::new();
    for value in value
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?
    {
        let id = value["job_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .filter(|id| ids.contains(id) && seen.insert(*id))
            .ok_or_else(invalid)?;
        if value["profile_version"] != *version
            || version
                .as_i64()
                .is_none_or(|v| v <= 0 || v > i32::MAX as i64)
        {
            return Err(invalid());
        }
        let score: DiscoveryMatch = serde_json::from_value(value.clone()).map_err(|_| invalid())?;
        if !score.match_score.is_finite()
            || !(0.0..=100.0).contains(&score.match_score)
            || score.explanation.len() > 16384
        {
            return Err(invalid());
        }
        for terms in [
            &score.matched_skills,
            &score.missing_skills,
            &score.positive_factors,
            &score.negative_factors,
            &score.exclusion_reasons,
            &score.unknown_fields,
        ] {
            if terms.len() > 200 || terms.iter().any(|v| v.len() > 4000) {
                return Err(invalid());
            }
        }
        let mut entry = serde_json::to_value(score).map_err(|_| invalid())?;
        entry["job_id"] = json!(id);
        entry["profile_version"] = version.clone();
        projected.push(entry);
    }
    let mut sorted = projected.clone();
    sorted.sort_by(|a, b| {
        b["match_score"]
            .as_f64()
            .unwrap_or(0.0)
            .total_cmp(&a["match_score"].as_f64().unwrap_or(0.0))
            .then_with(|| a["job_id"].as_str().cmp(&b["job_id"].as_str()))
    });
    if projected != sorted {
        return Err(invalid());
    }
    Ok(json!(projected))
}
