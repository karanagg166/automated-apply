//! Owner execution controls, preparation intents and retained outbox. No external IO.
use super::{
    contracts::{self, Kind},
    events, fences, filters, legacy_policy, legacy_questions, review,
    storage::*,
};
use crate::{Failure, Result, job_context::Reviewed};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

#[derive(Clone, Copy)]
pub enum Route<'a> {
    Summary,
    Configuration,
    AutomationPolicy,
    AutomationControl,
    Start,
    Import,
    Control(&'a str),
    Jobs,
    Events,
    Ack(&'a str),
    Questions,
    Ask(&'a str, &'a str),
    PacketAsk(&'a str, &'a str),
    Answer(&'a str),
    ReconcileDelivery(&'a str),
    ApproveReuse(&'a str),
    Reuse(&'a str, &'a str, &'a str),
}
impl Route<'_> {
    pub fn method(self) -> &'static str {
        match self {
            Self::Configuration | Self::AutomationPolicy => "PUT",
            Self::Summary | Self::Jobs | Self::Events | Self::Questions => "GET",
            _ => "POST",
        }
    }
    pub(super) fn kind(self) -> Option<Kind> {
        match self {
            Self::Configuration => Some(Kind::Configuration),
            Self::AutomationPolicy => Some(Kind::AutomationPolicyUpdate),
            Self::AutomationControl => Some(Kind::AutomationControl),
            Self::Start => Some(Kind::Start),
            Self::Import => Some(Kind::ImportBatch),
            Self::Control(_) => Some(Kind::ExecutionControl),
            Self::Answer(_) => Some(Kind::QuestionAnswer),
            _ => None,
        }
    }
    pub(super) fn input(self, body: &[u8]) -> Result<Option<Value>> {
        if matches!(self, Self::ReconcileDelivery(_)) {
            return super::telegram_reconciliation::normalize(
                serde_json::from_slice(body).map_err(|_| Failure("invalid_execution_contract"))?,
            )
            .map(Some);
        }
        if let Some(kind) = self.kind() {
            return contracts::normalize(
                kind,
                serde_json::from_slice(body).map_err(|_| Failure("invalid_execution_contract"))?,
            )
            .map(Some);
        }
        if matches!(self, Self::PacketAsk(..)) {
            let mut value: Value =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_execution_contract"))?;
            let object = value
                .as_object()
                .filter(|o| o.len() == 1 && o.contains_key("expected_revision"))
                .ok_or(Failure("invalid_execution_contract"))?;
            value["expected_revision"] = json!(
                crate::profile_contract::pagination_integer(
                    object["expected_revision"].clone(),
                    1,
                    2147483646
                )
                .map_err(|_| Failure("invalid_execution_contract"))?
            );
            return Ok(Some(value));
        }
        Ok(None)
    }
    pub fn status(self) -> u16 {
        if matches!(self, Self::Start) {
            202
        } else {
            200
        }
    }
}
pub fn route(path: &str) -> Option<Route<'_>> {
    let tail = path.strip_prefix("/api/v1/execution/")?;
    match tail {
        "naukri" => Some(Route::Summary),
        "naukri/automation/policy" => Some(Route::AutomationPolicy),
        "naukri/automation/control" => Some(Route::AutomationControl),
        "naukri/apply" => Some(Route::Start),
        "naukri/import" => Some(Route::Import),
        "naukri/jobs" => Some(Route::Jobs),
        "events" => Some(Route::Events),
        "questions" => Some(Route::Questions),
        _ => {
            let parts = tail.split('/').collect::<Vec<_>>();
            match parts.as_slice() {
                [id, "control"] if !id.is_empty() => Some(Route::Control(id)),
                ["events", id, "ack"] if !id.is_empty() => Some(Route::Ack(id)),
                ["questions", id, "answer"] if !id.is_empty() => Some(Route::Answer(id)),
                ["questions", id, "delivery-reconciliation"] if !id.is_empty() => {
                    Some(Route::ReconcileDelivery(id))
                }
                ["questions", id, "approve-reuse"] if !id.is_empty() => {
                    Some(Route::ApproveReuse(id))
                }
                [execution, "questions", field] if !execution.is_empty() && !field.is_empty() => {
                    Some(Route::Ask(execution, field))
                }
                ["packets", packet, "questions", field]
                    if !packet.is_empty() && !field.is_empty() =>
                {
                    Some(Route::PacketAsk(packet, field))
                }
                [execution, "questions", field, "reuse", source]
                    if !execution.is_empty() && !field.is_empty() && !source.is_empty() =>
                {
                    Some(Route::Reuse(execution, field, source))
                }
                _ => None,
            }
        }
    }
}
fn id(raw: &str) -> Result<Uuid> {
    raw.parse()
        .map_err(|_| Failure("invalid_execution_contract"))
}
fn terminal(value: &Value) -> bool {
    matches!(
        value["state"].as_str(),
        Some("REJECTED" | "FAILED_FINAL" | "SUBMITTED_CONFIRMED" | "SUBMISSION_UNKNOWN")
    )
}
pub(super) async fn intent_control_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    data: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let key = format!("exec:{identity}");
    let mut value = get(tx, &key).await?.ok_or(Failure("execution_not_found"))?;
    if value["id"] != identity.to_string() {
        return Err(invalid());
    }
    if value["revision"] != data["expected_revision"] {
        return Err(Failure("execution_revision_conflict"));
    }
    if terminal(&value) {
        return Err(Failure("execution_terminal_check_history"));
    }
    let action = data["action"]
        .as_str()
        .ok_or(Failure("invalid_execution_contract"))?;
    let state = if action == "resume" {
        legacy_policy::enabled(tx).await?;
        if let Some(revision) = legacy_policy::execution_in(tx, &value, now).await? {
            value["automation_revision"] = json!(revision);
        }
        if !matches!(value["state"].as_str(), Some("PAUSED" | "NEEDS_INPUT")) {
            return Err(Failure("execution_not_resumable"));
        }
        value["attempts"] = json!(0);
        if value["state"] == "PAUSED" {
            value["paused_state"].clone()
        } else {
            json!(if value["packet_id"].is_null() {
                "DISCOVERED"
            } else {
                "PREPARING"
            })
        }
    } else {
        value["paused_state"] = value["state"].clone();
        value["cancelled"] = json!(action == "cancel");
        json!(if value["state"] == "SUBMITTING" {
            "SUBMISSION_UNKNOWN"
        } else if action == "cancel" {
            "FAILED_FINAL"
        } else {
            "PAUSED"
        })
    };
    if !matches!(
        state.as_str(),
        Some(
            "DISCOVERED"
                | "MATCHED"
                | "ELIGIBLE"
                | "PREPARING"
                | "FILLING"
                | "NEEDS_INPUT"
                | "READY_FOR_REVIEW"
                | "PAUSED"
                | "FAILED_RETRYABLE"
                | "FAILED_FINAL"
                | "SUBMISSION_UNKNOWN"
        )
    ) {
        return Err(invalid());
    }
    value["state"] = state;
    value["revision"] = json!(next(&value)?);
    value["fence"] = json!(
        value["fence"]
            .as_i64()
            .filter(|n| *n >= 0)
            .and_then(|n| n.checked_add(1))
            .ok_or_else(invalid)?
    );
    value["lease_until"] = Value::Null;
    put(tx, &key, &value).await?;
    events::legacy(tx, &value, &format!("owner_{action}"), now).await?;
    Ok(value)
}
async fn configure_in(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    if data["submission_permission"] == true
        || data["destinations"]
            .as_array()
            .is_none_or(|a| !a.is_empty())
        || data["mode"] == "AUTO_APPLY_WHEN_AUTHORIZED"
    {
        return Err(Failure("naukri_submission_capability_not_verified"));
    }
    put(tx, "exec_config:naukri", &data).await?;
    if data["mode"] == "OFF" {
        fences::queue(tx, "global_stop", now).await?;
        let mut queue = super::queue_control::configuration(tx).await?;
        if revision(&queue)? > 0 {
            queue["state"] = json!("STOPPED");
            queue["revision"] = json!(next(&queue)?);
            put(tx, "application_queue_policy", &queue).await?;
        }
        // OFF historically stops every legacy execution, including question-only ATS contexts.
        let intents:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec:') AND value->>'state' NOT IN ('REJECTED','FAILED_FINAL','SUBMITTED_CONFIRMED','SUBMISSION_UNKNOWN','PAUSED') ORDER BY created_at,key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
        if intents.len() > 10000 {
            return Err(Failure("execution_active_inventory_limit"));
        }
        for value in intents {
            intent_control_in(
                tx,
                id(value["id"].as_str().ok_or_else(invalid)?)?,
                &json!({"action":"pause","expected_revision":value["revision"]}),
                now,
            )
            .await?;
        }
        fences::legacy(tx, "global_stop", now).await?;
        let mut automation = legacy_policy::record(tx).await?;
        if revision(&automation)? > 0 {
            automation["state"] = json!("STOPPED");
            automation["revision"] = json!(next(&automation)?);
            automation["next_check_at"] = Value::Null;
            put(tx, "naukri_automation", &automation).await?;
        }
    }
    Ok(data)
}
pub(super) async fn start_in(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    legacy_policy::enabled(tx).await?;
    let mut seen = std::collections::HashSet::new();
    let mut result = Vec::new();
    for raw in data["job_ids"].as_array().ok_or_else(invalid)? {
        let job_id = id(raw.as_str().ok_or_else(invalid)?)?;
        if !seen.insert(job_id) {
            continue;
        }
        let job: Value = sqlx::query_scalar(
            "SELECT to_jsonb(j) FROM jobs j WHERE id=$1 AND source_platform='naukri'",
        )
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("saved_naukri_job_required"))?;
        let url = filters::naukri_url(job["job_url"].as_str().ok_or_else(invalid)?)?;
        let company = if let Some(raw) = job["company_id"].as_str() {
            sqlx::query_scalar("SELECT jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) FROM companies c WHERE id=$1").bind(id(raw)?).fetch_optional(&mut **tx).await.map_err(db)?
        } else {
            None
        };
        let reviewed = Reviewed::new(job, company)?;
        let job = reviewed.job_view();
        let req = url.rsplit('-').next().ok_or_else(invalid)?;
        let identity = Uuid::new_v5(&Uuid::NAMESPACE_URL, format!("naukri:{req}").as_bytes());
        let key = format!("exec:{identity}");
        let value = if let Some(saved) = get(tx, &key).await? {
            saved
        } else {
            let value = json!({"id":identity,"attempt_id":Uuid::new_v4(),"job_id":job_id,"platform":"naukri","role":job["title"],"employer":reviewed.employer().map(|c|c["name"].clone()),"normalized_url":url,"requisition_id":req,"employer_id":job["company_id"],"state":"DISCOVERED","revision":1,"history":[],"evidence":[],"profile_version":null,"approved_answer_revisions":{},"packet_id":null,"fence":0,"attempts":0,"cancelled":false,"lease_until":null,"available_at":stamp(now),"heartbeat_at":null,"diagnostic":null,"created_at":stamp(now)});
            put(tx, &key, &value).await?;
            events::legacy(tx, &value, "intent_created", now).await?;
            value
        };
        result.push(value);
    }
    Ok(json!(result))
}
pub(super) async fn dispatch_in(
    tx: &mut Transaction<'_, Postgres>,
    route: Route<'_>,
    data: Option<Value>,
    telegram: bool,
    services: Option<legacy_questions::Services<'_>>,
    config: Option<&crate::configuration::Configuration>,
    now: DateTime<Utc>,
) -> Result<Value> {
    match route {
        Route::Summary => super::owner_status::status_in(tx, config, now).await,
        Route::Import => super::owner_import::import_in(tx, data.ok_or_else(invalid)?, now).await,
        Route::Questions => {
            let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec_q:') ORDER BY created_at,key").fetch_all(&mut **tx).await.map_err(db)?;
            Ok(json!(rows))
        }
        Route::Ask(execution, field) => {
            legacy_questions::ask_in(
                tx,
                id(execution)?,
                id(field)?,
                services.ok_or(Failure("execution_services_required"))?,
                now,
            )
            .await
        }
        Route::PacketAsk(packet, field) => {
            legacy_questions::ask_packet_in(
                tx,
                id(packet)?,
                id(field)?,
                data.as_ref()
                    .and_then(|d| d["expected_revision"].as_i64())
                    .ok_or(Failure("invalid_execution_contract"))?,
                services.ok_or(Failure("execution_services_required"))?,
                now,
            )
            .await
        }
        Route::Answer(raw) => {
            legacy_questions::answer_in(
                tx,
                id(raw)?,
                &data.ok_or_else(invalid)?,
                services.ok_or(Failure("execution_services_required"))?,
                now,
            )
            .await
        }
        Route::ReconcileDelivery(raw) => {
            super::telegram_reconciliation::reconcile_in(
                tx,
                id(raw)?,
                &data.ok_or_else(invalid)?,
                config
                    .and_then(|c| c.telegram.as_ref())
                    .ok_or(Failure("approved_telegram_channel_required"))?,
                now,
            )
            .await
        }
        Route::ApproveReuse(raw) => {
            legacy_questions::approve_in(
                tx,
                id(raw)?,
                services.ok_or(Failure("execution_services_required"))?,
                now,
            )
            .await
        }
        Route::Reuse(execution, field, source) => {
            legacy_questions::reuse_in(
                tx,
                id(source)?,
                id(execution)?,
                id(field)?,
                services.ok_or(Failure("execution_services_required"))?,
                now,
            )
            .await
        }
        Route::Configuration => configure_in(tx, data.ok_or_else(invalid)?, now).await,
        Route::AutomationPolicy => {
            legacy_policy::configure_in(tx, data.ok_or_else(invalid)?, telegram, now).await
        }
        Route::AutomationControl => {
            legacy_policy::control_in(tx, data.ok_or_else(invalid)?, now).await
        }
        Route::Start => start_in(tx, data.ok_or_else(invalid)?, now).await,
        Route::Control(raw) => {
            intent_control_in(tx, id(raw)?, &data.ok_or_else(invalid)?, now).await
        }
        Route::Jobs => Ok(
            json!({"jobs":review::jobs_in(tx,None,now).await?,"source":"owner_imports","portal_search_executed":false}),
        ),
        Route::Events => {
            let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec_event:') AND value->'delivered'='false'::jsonb ORDER BY created_at,key LIMIT 100").fetch_all(&mut **tx).await.map_err(db)?;
            Ok(json!(rows))
        }
        Route::Ack(raw) => {
            let key = format!("exec_event:{}", id(raw)?);
            let mut value = get(tx, &key)
                .await?
                .ok_or(Failure("execution_event_not_found"))?;
            value["delivered"] = json!(true);
            put(tx, &key, &value).await?;
            Ok(json!({"acknowledged":true}))
        }
    }
}
