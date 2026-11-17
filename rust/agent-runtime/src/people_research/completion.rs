//! Local-only completion from retained evidence. No grant, provider call or cost refund.
use super::{runs, settings::Settings};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("public_research_database_error")
}
pub async fn apply(
    c: &mut PgConnection,
    request: Uuid,
    settings: &Settings,
    contacts: &crate::contacts::Settings,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let before:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(runs::key(request)).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("public_research_request_not_found"))?;
    let before = before.ok_or(Failure("invalid_public_research_record"))?;
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = runs::time(&at)?;
    let original = runs::output(&before, request, now)?;
    if before["state"] != "finding_retained"
        || !matches!(
            before["finding"]["state"].as_str(),
            Some("success" | "partial" | "no_results")
        )
    {
        tx.commit().await.map_err(db)?;
        return Ok(original);
    }
    let observed = runs::time(&before["finding_at"])?;
    let input = crate::research_contract::normalize(
        crate::research_contract::Kind::PeopleQuery,
        before["input"].clone(),
        now,
    )?;
    if crate::startup_catalog::identity::content_hash(&input) != before["input_hash"] {
        return Err(Failure("public_research_finding_context_changed"));
    }
    let company_changed = match runs::company_in(&mut tx, &input).await {
        Ok(company) => company != before["company"],
        Err(e) if e.0 == "public_research_company_identity_ambiguous" => true,
        Err(e) => return Err(e),
    };
    let nonempty = before["finding"]["people"]
        .as_array()
        .is_none_or(|a| !a.is_empty());
    let reason = if before["configuration_hash"] != settings.context
        || before["retention_permission"] != json!(settings.permission)
    {
        Some("public_research_configuration_changed")
    } else if settings.require(&input).is_err() {
        Some("public_research_current_authorization_required")
    } else if observed > now || now - observed > chrono::Duration::hours(24) {
        Some("public_research_finding_expired")
    } else if nonempty && input["company_domain"].is_null() {
        Some("public_research_company_domain_required")
    } else if company_changed {
        Some("public_research_company_changed")
    } else {
        None
    };
    let mut expected = before.clone();
    if let Some(reason) = reason {
        expected["state"] = json!("held");
        expected["held_reason"] = json!(reason);
        expected["held_at"] = at;
    } else {
        let result =
            super::ingest::from_finding_in(&mut tx, &before, request, contacts, now).await?;
        expected["state"] = json!("completed");
        expected["completed_at"] = at;
        expected["result_hash"] = json!(crate::startup_catalog::identity::content_hash(&result));
        expected["result"] = result;
    }
    let actual:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 AND value=$3::jsonb RETURNING value").bind(&expected).bind(runs::key(request)).bind(&before).fetch_optional(&mut *tx).await.map_err(db)?;
    let saved: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(runs::key(request))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if actual.as_ref() != Some(&expected) || saved.as_ref() != Some(&expected) {
        return Err(Failure("public_research_write_ack_failed"));
    }
    if expected["state"] == "completed" {
        super::ingest::verify_completed_in(
            &mut tx,
            request,
            &before["input_hash"],
            &expected["result"],
        )
        .await?;
    }
    let value = runs::output(&expected, request, now)?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_research_commit_outcome_unknown"))?;
    Ok(value)
}
