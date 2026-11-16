//! Explicit owner-reviewed Naukri facts; import is not provider verification or submission authority.
use super::{filters, listing_ingestion, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Datelike, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
fn invalid() -> Failure {
    Failure("invalid_naukri_import")
}
/// Input has already passed ImportBatch's actual DTO. Normalize the factual record separately.
pub fn normalized(item: &Value, now: DateTime<Utc>) -> Result<Value> {
    let strip = |s: &str| {
        s.trim_matches(crate::context_contract::python_space)
            .to_owned()
    };
    let url =
        filters::naukri_url(item["url"].as_str().ok_or_else(invalid)?).map_err(|_| invalid())?;
    if item["provenance"] == "owner_job_alert"
        && item["message_reference"].as_str().is_none_or(str::is_empty)
    {
        return Err(invalid());
    }
    if item["experience_requirement"] == "required" && item["experience_min"].is_null() {
        return Err(invalid());
    }
    let posted = if item["posted_at"].is_null() {
        Value::Null
    } else {
        let at = timestamp(&item["posted_at"]).map_err(|_| invalid())?;
        if at.year() < 1990 || at > now + chrono::Duration::days(1) {
            return Err(invalid());
        }
        json!(stamp(at))
    };
    let canonical = crate::job_urls::ats(item["application_url"].as_str())?.unwrap_or(url.clone());
    let currency = item["salary_currency"].as_str().map(strip);
    if currency.as_deref().is_some_and(|s| {
        !matches!(s, "$" | "€" | "£")
            && (s.len() != 3 || !s.bytes().all(|b| b.is_ascii_uppercase()))
    }) {
        return Err(invalid());
    }
    for key in ["salary_min", "salary_max"] {
        if item[key].as_f64().is_some_and(|v| v > 1e12) {
            return Err(invalid());
        }
    }
    let mut out=listing_ingestion::normalized(&json!({"url":url,"requisition":url.rsplit('-').next()}),&json!({"requisition":url.rsplit('-').next(),"title":item["title"],"company":item["employer"],"description":item["description"],"location":item["location"],"skills":item["required_skills"],"experience_min":item["experience_min"],"experience_max":item["experience_max"],"posted_at":posted,"remote_type":item["remote_type"],"employment_type":item["employment_type"],"salary_min":item["salary_min"],"salary_max":item["salary_max"],"salary_currency":currency,"salary_period":item["salary_period"]}),now).map_err(|_|invalid())?;
    out["canonical_url"] = json!(canonical);
    out["application_url"] = item["application_url"].clone();
    out["source_verification_status"] = json!("requires_review");
    out["skills_preferred"] = item["preferred_skills"].clone();
    for key in ["title", "company_name", "description", "location"] {
        if let Some(s) = out[key].as_str() {
            out[key] = json!(strip(s));
        }
    }
    for key in ["skills_required", "skills_preferred"] {
        out[key] = json!(
            out[key]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .map(|v| v.as_str().map(strip).ok_or_else(invalid))
                .collect::<Result<Vec<_>>>()?
        );
    }
    out["data_provenance"] = json!({"method":item["provenance"],"reference":item["message_reference"],"experience_requirement":item["experience_requirement"],"provider_verified":false,"posting_status":item["posting_status"],"owner_observed_at":item["observed_at"],"valid_through":item["valid_through"]});
    Ok(out)
}
pub(super) async fn import_in(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut items = Vec::new();
    for raw in data["jobs"].as_array().ok_or_else(invalid)? {
        let mut item = raw.clone();
        if let Some(raw) = item["alert_candidate_id"].as_str() {
            let id = raw.parse::<Uuid>().map_err(|_| invalid())?;
            let key = format!("nau_alert:{id}");
            let mut candidate = get(tx, &key).await?.ok_or_else(invalid)?;
            if candidate["state"] != "NEEDS_INPUT"
                || timestamp(&candidate["expires_at"]).map_err(|_| invalid())? <= now
                || filters::naukri_url(item["url"].as_str().ok_or_else(invalid)?)
                    .map_err(|_| invalid())?
                    != candidate["url"].as_str().ok_or_else(invalid)?
            {
                return Err(invalid());
            }
            item["provenance"] = json!("owner_job_alert");
            item["message_reference"] = json!(format!("gmail-alert:{id}"));
            candidate["state"] = json!("OWNER_REVIEWED");
            candidate["reviewed_at"] = json!(stamp(now));
            put(tx, &key, &candidate).await?;
        }
        items.push(normalized(&item, now)?);
    }
    let mut inserted = 0;
    let mut updated = 0;
    let mut rejected = 0;
    let mut ids = Vec::new();
    let mut possible = serde_json::Map::new();
    let mut errors = Vec::new();
    for (index, item) in items.iter().enumerate() {
        let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
        match listing_ingestion::save_owner_in(&mut savepoint, item).await {
            Ok((saved, created)) => {
                if created {
                    let candidates:Vec<(Uuid,String)>=sqlx::query_as("SELECT id,title FROM jobs WHERE company_id=$1 AND id!=$2 ORDER BY id LIMIT 500").bind(saved["company_id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).bind(saved["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).fetch_all(&mut *savepoint).await.map_err(db)?;
                    let text = |raw: &str| {
                        static HTML: std::sync::LazyLock<regex::Regex> =
                            std::sync::LazyLock::new(|| {
                                regex::Regex::new("<[^>]*>").expect("fixed title cleanup")
                            });
                        automated_apply_domain::text::folded(&HTML.replace_all(raw, " "))
                            .split(crate::context_contract::python_space)
                            .filter(|s| !s.is_empty())
                            .collect::<Vec<_>>()
                            .join(" ")
                    };
                    let title = text(item["title"].as_str().ok_or_else(invalid)?);
                    let hints = candidates
                        .into_iter()
                        .filter(|(_, raw)| text(raw) == title)
                        .take(20)
                        .map(|(id, _)| id.to_string())
                        .collect::<Vec<_>>();
                    if !hints.is_empty() {
                        possible.insert(
                            saved["id"].as_str().ok_or_else(invalid)?.to_owned(),
                            json!(hints),
                        );
                    }
                }
                savepoint.commit().await.map_err(db)?;
                ids.push(saved["id"].as_str().ok_or_else(invalid)?.to_owned());
                if created {
                    inserted += 1;
                } else {
                    updated += 1;
                }
            }
            Err(Failure("job_identity_requires_review")) => {
                savepoint
                    .rollback()
                    .await
                    .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
                rejected += 1;
                errors.push(format!("Record {index}: conflicting identity evidence"));
            }
            Err(error) => {
                savepoint
                    .rollback()
                    .await
                    .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
                return Err(error);
            }
        }
    }
    Ok(
        json!({"total_received":items.len(),"inserted_count":inserted,"updated_count":updated,"duplicate_count":updated,"rejected_count":rejected,"failed_count":0,"skipped_count":rejected,"job_ids":ids,"possible_duplicates":possible,"errors":errors}),
    )
}
