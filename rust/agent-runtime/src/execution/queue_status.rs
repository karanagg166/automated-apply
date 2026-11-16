//! Coherent read-only queue projection. No owner lock, authority mutation, full history payload or provider IO.
use super::{
    contracts::{self, Kind},
    queue_page::Page,
    storage::*,
};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};

pub(super) fn configuration(saved: Option<&Value>) -> Result<Value> {
    let mut value = saved
        .cloned()
        .unwrap_or(json!({"revision":0,"state":"STOPPED","policy":{}}));
    revision(&value)?;
    if !matches!(
        value["state"].as_str(),
        Some("STOPPED" | "PAUSED" | "RUNNING")
    ) {
        return Err(invalid());
    }
    value["policy"] =
        contracts::normalize(Kind::Policy, value["policy"].clone()).map_err(|_| invalid())?;
    Ok(value)
}
pub(super) async fn listing(tx: &mut Transaction<'_, Postgres>, page: Page) -> Result<Value> {
    let metadata:Value=sqlx::query_scalar("SELECT jsonb_build_object('at',clock_timestamp(),'preferences',coalesce(jsonb_object_agg(key,value),'{}'::jsonb)) FROM owner_preferences WHERE key IN ('application_queue_policy','apply_search:naukri','apply_consumer:naukri')").fetch_one(&mut **tx).await.map_err(db)?;
    let records = &metadata["preferences"];
    let config = configuration(records.get("application_queue_policy"))?;
    let policy = &config["policy"];
    let now = timestamp(&metadata["at"])?;
    let day = contracts::day_bucket(now, policy["day_timezone"].as_str().ok_or_else(invalid)?)?;
    let effective = contracts::limits(policy, "naukri")?;
    let setting = &policy["platforms"]["naukri"];
    let mut cap = effective["daily_cap"].as_i64().ok_or_else(invalid)?;
    if setting["mode"] == "SUPERVISED" {
        cap = cap.min(
            setting["supervised_submission_cap"]
                .as_i64()
                .ok_or_else(invalid)?,
        );
    }
    let mut data: Value = sqlx::query_scalar(include_str!("../../sql/execution_queue_status.sql"))
        .bind(page.platform)
        .bind(page.stage)
        .bind(
            page.search
                .as_ref()
                .filter(|s| !s.is_empty())
                .map(|s| format!("%{s}%")),
        )
        .bind(
            page.location
                .as_ref()
                .filter(|s| !s.is_empty())
                .map(|s| format!("%{s}%")),
        )
        .bind(page.minimum_score)
        .bind(page.offset)
        .bind(page.limit)
        .bind(format!("apply_budget:naukri:{day}"))
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let budget = data
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("budget")
        .ok_or_else(invalid)?;
    let used = if budget.is_null() {
        0
    } else {
        budget["used"]
            .as_i64()
            .filter(|n| *n >= 0)
            .ok_or_else(invalid)?
    };
    let project = |key: &str, fields: &[&str]| -> Value {
        records
            .get(key)
            .map(|record| {
                json!(
                    fields
                        .iter()
                        .map(|k| (k.to_string(), record[k].clone()))
                        .collect::<serde_json::Map<String, Value>>()
                )
            })
            .unwrap_or(Value::Null)
    };
    data["limit"] = json!(page.limit);
    data["offset"] = json!(page.offset);
    data["configuration"] = config.clone();
    data["discovery"] = project(
        "apply_search:naukri",
        &[
            "last_started_at",
            "last_finished_at",
            "next_at",
            "last_cycle_count",
            "last_error",
        ],
    );
    data["consumer"] = project(
        "apply_consumer:naukri",
        &["last_poll_at", "busy", "capability"],
    );
    data["quota"] = json!({"reserved_today":used,"daily_cap":cap,"remaining":(cap-used).max(0),"hourly_cap":setting["hourly_submission_cap"]});
    data["capabilities"] = json!({"background_read":"implemented_not_live_accepted","submission":"unavailable","locked_screen":"NOT_TESTED","queue":"existing_postgresql"});
    Ok(data)
}
pub(super) async fn account(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let value = get(tx, "naukri_account_binding")
        .await?
        .unwrap_or(json!({"revision":0,"approved":false}));
    revision(&value)?;
    if !value["approved"].is_boolean() {
        return Err(Failure("invalid_execution_saved_record"));
    }
    Ok(value)
}
