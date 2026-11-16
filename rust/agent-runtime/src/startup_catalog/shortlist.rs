//! Original saved company shortlist. Replay preserves the first snapshot, note and run.
use super::{
    contract::{self, Kind},
    detail,
};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_catalog_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_startup_catalog_record")
}
pub(crate) fn public_snapshot(snapshot: &Value) -> Result<Value> {
    if !snapshot.is_object() {
        return Err(invalid());
    }
    let mut output = json!({});
    for key in [
        "company_id",
        "company_name",
        "company_domain",
        "identity_review_required",
        "employee_count",
        "team_size_band",
        "team_size_evidence_status",
        "hiring_status",
        "startup_match_score",
        "current_job_count",
        "leader_evidence_count",
        "technical_staff_count",
        "professional_contact_count",
        "qualified_business_mailbox_count",
        "contact_inventory_count",
        "available_evidence_count",
        "shortlisted",
        "matching_roles",
        "profile_version",
        "score_kind",
        "evidence_basis",
        "live_verified",
        "profile_basis",
    ] {
        if let Some(v) = snapshot.get(key) {
            if v.is_object() || v.is_array() || v.as_str().is_some_and(|s| s.len() > 1020) {
                return Err(invalid());
            }
            output[key] = v.clone();
        }
    }
    output["attributes"] = crate::companies::attributes(&snapshot["attributes"])?;
    for key in [
        "sources",
        "ranking_reasons",
        "missing_information",
        "exclusion_reasons",
    ] {
        if let Some(v) = snapshot.get(key) {
            if !v.as_array().is_some_and(|a| {
                a.len() <= 100
                    && a.iter()
                        .all(|s| s.as_str().is_some_and(|s| s.len() <= 2000))
            }) {
                return Err(invalid());
            }
            output[key] = v.clone();
        }
    }
    for (key, fields, max) in [
        (
            "team_size_evidence",
            &[
                "source",
                "source_url",
                "observed_at",
                "historical",
                "employee_count",
                "band",
                "verification_status",
                "future_observation_requires_review",
            ][..],
            20,
        ),
        (
            "hiring_evidence",
            &[
                "job_id",
                "title",
                "source",
                "evidence_url",
                "posted_at",
                "observed_at",
                "fresh",
                "hiring_status",
                "location",
                "remote_policy",
                "verification_status",
            ][..],
            500,
        ),
        (
            "hiring_statement_evidence",
            &["source", "evidence_url", "observed_at", "status"][..],
            20,
        ),
    ] {
        let rows = snapshot[key]
            .as_array()
            .filter(|a| a.len() <= max)
            .ok_or_else(invalid)?;
        let mut safe = Vec::new();
        for row in rows {
            let mut item = json!({});
            for field in fields {
                if let Some(v) = row.get(*field) {
                    if v.is_object() || v.is_array() || v.as_str().is_some_and(|s| s.len() > 2048) {
                        return Err(invalid());
                    }
                    item[*field] =
                        if matches!(*field, "source_url" | "evidence_url") && !v.is_null() {
                            json!(
                                v.as_str()
                                    .and_then(crate::resources::public_https)
                                    .ok_or_else(invalid)?
                            )
                        } else {
                            v.clone()
                        };
                }
            }
            safe.push(item);
        }
        output[key] = json!(safe);
    }
    Ok(output)
}
pub fn route(path: &str) -> Option<Uuid> {
    path.strip_prefix("/api/v1/startups/")?
        .strip_suffix("/shortlist")?
        .parse()
        .ok()
}
async fn get_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let row:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(s)::text)<=2097152 THEN to_jsonb(s) ELSE NULL END FROM startup_shortlist_entries s WHERE company_id=$1 FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    row.map(|v| v.ok_or_else(invalid)).transpose()
}
pub async fn save(
    c: &mut PgConnection,
    id: Uuid,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    if method != "POST" {
        return Err(Failure("startup_catalog_method_not_allowed"));
    }
    if query.is_some() {
        return Err(Failure("invalid_startup_query"));
    }
    let input = contract::normalize(
        Kind::Shortlist,
        serde_json::from_slice(body).map_err(|_| Failure("invalid_startup_contract"))?,
    )?;
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let found: Option<Uuid> = sqlx::query_scalar("SELECT id FROM companies WHERE id=$1 FOR SHARE")
        .bind(id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
    if found.is_none() {
        return Err(Failure("startup_catalog_not_found"));
    }
    if let Some(existing) = get_in(&mut tx, id).await? {
        if !existing["snapshot"].is_object() {
            return Err(invalid());
        }
        let result = json!({"company_id":id,"created":false,"snapshot":public_snapshot(&existing["snapshot"] )?,"preserved_original":true});
        tx.commit()
            .await
            .map_err(|_| Failure("startup_catalog_commit_outcome_unknown"))?;
        return Ok(result);
    }
    if let Some(run) = input["run_id"].as_str() {
        let run = run.parse::<Uuid>().map_err(|_| invalid())?;
        let found:Option<Uuid>=sqlx::query_scalar("SELECT id FROM discovery_runs WHERE id=$1 AND starts_with(source,'startup_') FOR SHARE").bind(run).fetch_optional(&mut *tx).await.map_err(db)?;
        if found.is_none() {
            return Err(Failure("startup_catalog_run_not_found"));
        }
    }
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = chrono::DateTime::parse_from_rfc3339(stamp.as_str().ok_or_else(invalid)?)
        .map_err(|_| invalid())?
        .to_utc();
    let filters = contract::normalize(Kind::Filters, json!({"max_employees":null}))?;
    let profile = detail::profile_in(&mut tx, true).await?;
    let snapshot = detail::load_in(&mut tx, id, &filters, profile.as_ref(), settings, now).await?;
    let expected = json!({"company_id":id,"run_id":input["run_id"],"snapshot":snapshot,"note":input["note"],"created_at":stamp});
    if expected.to_string().len() > 2097152 {
        return Err(Failure("startup_catalog_projection_limit"));
    }
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO startup_shortlist_entries AS s(company_id,run_id,snapshot,note,created_at) VALUES($1,($2::jsonb->>'run_id')::uuid,$2::jsonb->'snapshot',$2::jsonb->>'note',($2::jsonb->>'created_at')::timestamptz) ON CONFLICT DO NOTHING RETURNING to_jsonb(s)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if ack.as_ref() != Some(&expected) || get_in(&mut tx, id).await?.as_ref() != Some(&expected) {
        return Err(Failure("startup_catalog_write_ack_failed"));
    }
    let result = json!({"company_id":id,"created":true,"snapshot":public_snapshot(&snapshot)?,"preserved_original":false});
    tx.commit()
        .await
        .map_err(|_| Failure("startup_catalog_commit_outcome_unknown"))?;
    Ok(result)
}
