//! Retain selected transport evidence before local ingestion. No request replay or refund.
use super::{
    runs::{self, Claim},
    transport::Outcome,
};
use crate::{
    Failure, Result,
    contacts::enrichment::budget,
    research_contract::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
fn db(_: sqlx::Error) -> Failure {
    Failure("public_research_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_public_research_record")
}
fn ack() -> Failure {
    Failure("public_research_write_ack_failed")
}
pub(super) fn selected(journal: &Value, now: DateTime<Utc>) -> Result<Value> {
    let finding = &journal["finding"];
    let state = finding["state"]
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "success"
                    | "partial"
                    | "no_results"
                    | "authentication_required"
                    | "rate_limited"
                    | "upstream_error"
                    | "outcome_unknown"
                    | "not_dispatched"
            )
        })
        .ok_or_else(invalid)?;
    if finding["request_attempted"].as_bool().is_none()
        || finding["response_observed"].as_bool().is_none()
        || finding.to_string().len() > 262144
        || journal["finding_hash"] != crate::startup_catalog::identity::content_hash(finding)
    {
        return Err(invalid());
    }
    let rows = finding["people"]
        .as_array()
        .filter(|a| a.len() <= 20)
        .ok_or_else(invalid)?;
    if !matches!(state, "success" | "partial" | "no_results") && !rows.is_empty() {
        return Err(invalid());
    }
    let mut people = Vec::new();
    for p in rows {
        if journal["input"]["research_mode"] == "official_company" {
            let p = research_contract::normalize(Kind::OfficialPerson, p.clone(), now)?;
            if p["human_confirmed"] != false
                || !p["business_email"].is_null()
                || !p["email_publication_url"].is_null()
            {
                return Err(invalid());
            }
            people.push(json!({"full_name":p["full_name"],"role_title":p["role_title"],"evidence_url":p["evidence_url"],"observed_at":p["observed_at"],"human_confirmed":false,"verification_status":"requires_review"}));
        } else {
            let p = research_contract::normalize(Kind::PublicPerson, p.clone(), now)?;
            if p["source"] != "public_search" {
                return Err(invalid());
            }
            people.push(p);
        }
    }
    let errors = finding["errors"]
        .as_array()
        .filter(|a| a.len() <= 20 && a.iter().all(|s| s == "public_search_record_invalid"))
        .ok_or_else(invalid)?
        .clone();
    let code = match finding["code"].as_str() {
        None if finding["code"].is_null() => None,
        Some(s)
            if matches!(
                s,
                "public_research_original_dispatch_unconfirmed"
                    | "public_research_original_grant_expired_or_changed"
                    | "public_research_original_grant_changed"
                    | "public_research_rate_limited"
                    | "public_research_provider_authentication_required"
                    | "public_research_http_unavailable"
                    | "public_research_response_limit"
                    | "public_research_invalid_provider_response"
            ) =>
        {
            Some(s)
        }
        _ => return Err(invalid()),
    };
    let retry = match finding["retry_after_seconds"].as_i64() {
        None if finding["retry_after_seconds"].is_null() => None,
        Some(s) if (1..=86400).contains(&s) => Some(s),
        _ => return Err(invalid()),
    };
    Ok(
        json!({"provider_status":state,"people":people,"errors":errors,"failure_code":code,"retry_after_seconds":retry,"provider_request_attempted":finding["request_attempted"],"provider_response_retained":finding["response_observed"],"finding_retained":true,"persistence_status":"not_imported"}),
    )
}
pub(super) async fn retain(
    c: &mut PgConnection,
    claim: &Claim,
    outcome: &Outcome,
) -> Result<Value> {
    if outcome.request != claim.id || claim.journal["invocation"] != json!(outcome.invocation) {
        return Err(Failure("public_research_finding_context_changed"));
    }
    let finding = json!({"state":outcome.state,"code":outcome.code,"people":outcome.people,"errors":outcome.errors,"retry_after_seconds":outcome.retry,"request_attempted":outcome.attempted,"response_observed":outcome.response_observed});
    let hash = crate::startup_catalog::identity::content_hash(&finding);
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = runs::time(&at)?;
    let saved:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(runs::key(claim.id)).fetch_optional(&mut *tx).await.map_err(db)?.ok_or_else(invalid)?;
    let before = saved.ok_or_else(invalid)?;
    if before != claim.journal {
        let mut original = before.clone();
        let obj = original.as_object_mut().ok_or_else(invalid)?;
        for key in ["finding", "finding_hash", "finding_at"] {
            obj.remove(key);
        }
        original["state"] = json!("dispatch_admitted");
        original["provider_response_retained"] =
            claim.journal["provider_response_retained"].clone();
        if original != claim.journal
            || before["finding_hash"] != hash
            || before["state"] != "finding_retained"
        {
            return Err(Failure("public_research_finding_context_changed"));
        }
        let value = runs::output(&before, claim.id, now)?;
        tx.commit().await.map_err(db)?;
        return Ok(value);
    }
    let terminal = match outcome.state {
        "success" | "partial" | "no_results" => "completed",
        "rate_limited" => "rate_limited",
        "authentication_required" => "authorization_required",
        "outcome_unknown" => "billing_uncertain",
        _ => "failed",
    };
    budget::finish_in(&mut tx, &claim.reservation, terminal, None, None).await?;
    if outcome.state == "rate_limited" {
        budget::cooldown_in(
            &mut tx,
            "serper",
            outcome.retry.unwrap_or(60).clamp(1, 86400),
        )
        .await?;
    }
    let mut expected = before.clone();
    expected["state"] = json!("finding_retained");
    expected["finding"] = finding;
    expected["finding_hash"] = json!(hash);
    expected["finding_at"] = at;
    expected["provider_response_retained"] = json!(outcome.response_observed);
    selected(&expected, now)?;
    let actual:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 AND value=$3::jsonb RETURNING value").bind(&expected).bind(runs::key(claim.id)).bind(&before).fetch_optional(&mut *tx).await.map_err(db)?;
    let retained: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(runs::key(claim.id))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if actual.as_ref() != Some(&expected) || retained.as_ref() != Some(&expected) {
        return Err(ack());
    }
    budget::finish_in(&mut tx, &claim.reservation, terminal, None, None).await?;
    let value = runs::output(&expected, claim.id, now)?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_research_commit_outcome_unknown"))?;
    Ok(value)
}
