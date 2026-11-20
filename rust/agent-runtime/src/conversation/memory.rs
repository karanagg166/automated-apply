//! Bounded private selection memory; callers verify actor/bot binding and roll back on errors.
use super::intent::Intent;
use crate::{Failure, Result};
use chrono::{DateTime, Duration, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("conversation_memory_database_error")
}
fn invalid() -> Failure {
    Failure("conversation_memory_review_required")
}
fn ack() -> Failure {
    Failure("conversation_memory_write_ack_failed")
}
fn time(value: &Value) -> Result<DateTime<Utc>> {
    value
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|v| v.to_utc())
        .ok_or_else(invalid)
}
fn uuid(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .filter(|id: &Uuid| !id.is_nil())
        .ok_or_else(invalid)
}
fn fresh() -> Value {
    json!({"conversation_id":Uuid::new_v4(),"history":[],"job_ids":[],"selected_job_id":null,"project_id":null,"clarification":null})
}
fn checked(value: &Value) -> Result<()> {
    let fields = value
        .as_object()
        .filter(|m| m.len() <= 12 && value.to_string().len() <= 32768)
        .ok_or_else(invalid)?;
    let allowed = [
        "conversation_id",
        "history",
        "job_ids",
        "selected_job_id",
        "project_id",
        "clarification",
        "intent",
        "prepare",
        "current_company",
        "expires_at",
        "project_rank",
        "answer_question",
    ];
    if fields.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid());
    }
    uuid(&value["conversation_id"])?;
    let ids = value["job_ids"]
        .as_array()
        .filter(|a| a.len() <= 10)
        .ok_or_else(invalid)?
        .iter()
        .map(uuid)
        .collect::<Result<Vec<_>>>()?;
    if ids.iter().collect::<std::collections::BTreeSet<_>>().len() != ids.len() {
        return Err(invalid());
    }
    if !value["selected_job_id"].is_null() && !ids.contains(&uuid(&value["selected_job_id"])?) {
        return Err(invalid());
    }
    if !value["project_id"].is_null() {
        uuid(&value["project_id"])?;
    }
    if !value["clarification"].is_null() && value["clarification"] != "choose_one_request" {
        return Err(invalid());
    }
    let history = value["history"]
        .as_array()
        .filter(|a| a.len() <= 8)
        .ok_or_else(invalid)?;
    for item in history {
        let item = item
            .as_object()
            .filter(|m| m.len() == 2)
            .ok_or_else(invalid)?;
        let category = item
            .get("category")
            .and_then(Value::as_str)
            .filter(|s| {
                [
                    "GENERAL_CHAT",
                    "UNSUPPORTED_ACTION",
                    "JOB_DISCOVERY",
                    "JOB_FILTERING",
                    "FOLLOW_UP",
                    "APPLICATION_PREPARATION",
                    "APPLICATION_STATUS",
                    "CONNECTION_STATUS",
                    "FOUNDER_RESEARCH",
                    "PROJECT_QUERY",
                    "PROFILE_QUERY",
                    "RESUME_STATUS",
                    "APPROVAL_REQUEST",
                    "JOB_COMPARISON",
                ]
                .contains(s)
            })
            .ok_or_else(invalid)?;
        let _ = category;
        time(item.get("at").ok_or_else(invalid)?)?;
    }
    for (key, max) in [("current_company", 100), ("answer_question", 200)] {
        if !value[key].is_null()
            && value[key].as_str().is_none_or(|s| {
                s.is_empty() || s.chars().count() > max || s.chars().any(char::is_control)
            })
        {
            return Err(invalid());
        }
    }
    if !value["project_rank"].is_null()
        && value["project_rank"]
            .as_u64()
            .is_none_or(|n| !(1..=30).contains(&n))
    {
        return Err(invalid());
    }
    if fields.get("prepare").is_some_and(|v| !v.is_boolean()) {
        return Err(invalid());
    }
    if !value["intent"].is_null() {
        super::intent::normalize(value["intent"].clone()).map_err(|_| invalid())?;
    }
    if fields.contains_key("expires_at") {
        time(&value["expires_at"])?;
    }
    Ok(())
}
/// The original saved row is retained privately; this is not a provider or action grant.
pub struct Loaded {
    key: String,
    expected: Option<Value>,
    value: Value,
}
impl Loaded {
    pub fn value(&self) -> &Value {
        &self.value
    }
    pub fn conversation_id(&self) -> Result<Uuid> {
        uuid(&self.value["conversation_id"])
    }
}
async fn raw(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=32768 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(key).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("conversation_memory_saved_limit")),
        None => Ok(None),
    }
}
async fn now(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
pub(crate) enum Scope {
    Dashboard,
    Telegram(i64),
}

pub async fn load_in(tx: &mut Transaction<'_, Postgres>, owner: i64) -> Result<Loaded> {
    load_scope_in(tx, Scope::Telegram(owner)).await
}

pub(crate) async fn load_scope_in(
    tx: &mut Transaction<'_, Postgres>,
    scope: Scope,
) -> Result<Loaded> {
    let key = match scope {
        Scope::Dashboard => "dashboard_conversation:primary".into(),
        Scope::Telegram(owner) if owner > 0 => crate::telegram_local::context_key(owner),
        Scope::Telegram(_) => return Err(Failure("conversation_owner_binding_required")),
    };
    crate::execution::lock_owner_in(tx).await?;
    let saved = raw(tx, &key).await?;
    let now = now(tx).await?;
    let value = if let Some(saved) = &saved {
        checked(saved)?;
        let expires = time(&saved["expires_at"])?;
        if expires > now + Duration::minutes(11) {
            return Err(invalid());
        }
        if expires <= now {
            fresh()
        } else {
            saved.clone()
        }
    } else {
        fresh()
    };
    Ok(Loaded {
        key,
        expected: saved,
        value,
    })
}
pub async fn save_in(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut Loaded,
    value: Value,
) -> Result<()> {
    persist_in(tx, loaded, value, false).await
}
async fn persist_in(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut Loaded,
    mut value: Value,
    reset: bool,
) -> Result<()> {
    crate::execution::lock_owner_in(tx).await?;
    checked(&value)?;
    if !reset && uuid(&value["conversation_id"])? != loaded.conversation_id()? {
        return Err(Failure("conversation_identity_changed"));
    }
    if raw(tx, &loaded.key).await? != loaded.expected {
        return Err(Failure("conversation_memory_changed"));
    }
    value["expires_at"] = json!(now(tx).await? + Duration::minutes(10));
    checked(&value)?;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(&loaded.key).bind(&value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&value) || raw(tx, &loaded.key).await?.as_ref() != Some(&value) {
        return Err(ack());
    }
    loaded.expected = Some(value.clone());
    loaded.value = value;
    Ok(())
}
pub async fn record_in(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut Loaded,
    intent: &Intent,
) -> Result<()> {
    let mut value = loaded.value.clone();
    let mut history = value["history"].as_array().ok_or_else(invalid)?.clone();
    history.push(json!({"category":intent.routing_category(),"at":now(tx).await?}));
    if history.len() > 8 {
        history.drain(..history.len() - 8);
    }
    value["history"] = json!(history);
    save_in(tx, loaded, value).await
}
pub async fn reset_in(tx: &mut Transaction<'_, Postgres>, loaded: &mut Loaded) -> Result<()> {
    // An explicit reset changes only bounded selection memory, never application history.
    persist_in(tx, loaded, fresh(), true).await
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fresh_and_legacy_selection_shapes_are_bounded_and_have_no_raw_message_field() {
        let value = fresh();
        assert!(checked(&value).is_ok());
        let mut value = value;
        value["intent"] = json!({"category":"FIND_JOBS"});
        value["prepare"] = json!(true);
        value["current_company"] = json!("Fictional Labs");
        assert!(checked(&value).is_ok());
        value["raw_message"] = json!("private input");
        assert!(checked(&value).is_err());
    }
    #[test]
    fn jobs_are_unique_nonnil_bounded_and_selection_must_belong_to_original_list() {
        let mut value = fresh();
        let id = Uuid::new_v4();
        value["job_ids"] = json!([id]);
        value["selected_job_id"] = json!(id);
        assert!(checked(&value).is_ok());
        value["selected_job_id"] = json!(Uuid::new_v4());
        assert!(checked(&value).is_err());
        value["selected_job_id"] = Value::Null;
        value["job_ids"] = json!([id, id]);
        assert!(checked(&value).is_err());
        value["job_ids"] = json!([Uuid::nil()]);
        assert!(checked(&value).is_err());
        value["job_ids"] = json!((0..11).map(|_| Uuid::new_v4()).collect::<Vec<_>>());
        assert!(checked(&value).is_err());
    }
    #[test]
    fn history_contains_only_bounded_known_categories_and_parseable_timestamps() {
        let mut value = fresh();
        value["history"] = json!([{"category":"JOB_DISCOVERY","at":"2026-11-17T10:00:00Z"}]);
        assert!(checked(&value).is_ok());
        value["history"][0]["category"] = json!("SUBMIT_APPLICATION");
        assert!(checked(&value).is_err());
        value["history"][0]["category"] = json!("FOLLOW_UP");
        value["history"][0]["message"] = json!("private");
        assert!(checked(&value).is_err());
        value["history"] = json!(vec![
            json!({"category":"FOLLOW_UP","at":"2026-11-17T10:00:00Z"});
            9
        ]);
        assert!(checked(&value).is_err());
    }
    #[test]
    fn malformed_intents_rank_flags_and_private_question_controls_are_refused() {
        for (key, item) in [
            ("prepare", json!("true")),
            ("project_rank", json!(31)),
            ("answer_question", json!("question\nprivate")),
            ("clarification", json!("execute")),
            ("intent", json!({"category":"FIND_JOBS","submit":true})),
            ("conversation_id", json!(Uuid::nil())),
        ] {
            let mut value = fresh();
            value[key] = item;
            assert!(checked(&value).is_err());
        }
    }
}
