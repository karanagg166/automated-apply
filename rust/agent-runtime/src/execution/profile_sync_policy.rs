//! Owner profile-sync controls and coherent reference-only status. No portal action or scope reset.
use super::{
    contracts::{self, Kind},
    storage::*,
};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn configuration_in(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let value = get(tx, "naukri_profile_sync_policy").await?.unwrap_or(
        json!({"revision":0,"policy":contracts::normalize(Kind::SyncPolicy,json!({}))?}),
    );
    revision(&value)?;
    contracts::normalize(Kind::SyncPolicy, value["policy"].clone()).map_err(|_| invalid())?;
    Ok(value)
}
fn confirmed(profile: Option<&Value>, confirmation: Option<&Value>) -> bool {
    profile.zip(confirmation).is_some_and(|(p, c)| {
        p["id"] == c["profile_id"]
            && p["version"] == c["profile_version"]
            && c["confirmed_at"].as_str().is_some_and(|s| !s.is_empty())
    })
}
pub(super) async fn status_in(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let profile:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'version',version) FROM candidate_profiles WHERE singleton_key='primary'").fetch_optional(&mut **tx).await.map_err(db)?;
    let values:Value=sqlx::query_scalar("SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM owner_preferences WHERE key IN ('naukri_profile_sync_policy','apply_profile_sync:naukri','phase1_profile_confirmation') OR key='nau_sync:'||(SELECT value->>'last_record' FROM owner_preferences WHERE key='apply_profile_sync:naukri')").fetch_one(&mut **tx).await.map_err(db)?;
    let configuration = values.get("naukri_profile_sync_policy").cloned().unwrap_or(
        json!({"revision":0,"policy":contracts::normalize(Kind::SyncPolicy,json!({}))?}),
    );
    revision(&configuration)?;
    contracts::normalize(Kind::SyncPolicy, configuration["policy"].clone())
        .map_err(|_| invalid())?;
    let work = &values["apply_profile_sync:naukri"];
    let latest = match work["last_record"].as_str() {
        Some(id) => {
            id.parse::<Uuid>().map_err(|_| invalid())?;
            values
                .get(format!("nau_sync:{id}").as_str())
                .cloned()
                .unwrap_or(Value::Null)
        }
        None if work["last_record"].is_null() => Value::Null,
        _ => return Err(invalid()),
    };
    if !work["last_error"].is_null() && !work["last_error"].is_string() {
        return Err(invalid());
    }
    Ok(
        json!({"configuration":configuration,"latest":latest,"current_profile_version":profile.as_ref().map(|p|p["version"].clone()),"profile_confirmed":confirmed(profile.as_ref(),values.get("phase1_profile_confirmation")),"last_error":work["last_error"],"supported_updates":["skills","summary"],"live_accepted":false}),
    )
}
pub(super) async fn configure_in(
    tx: &mut Transaction<'_, Postgres>,
    input: Value,
) -> Result<Value> {
    let current = configuration_in(tx).await?;
    if current["revision"] != input["expected_revision"] {
        return Err(Failure("profile_sync_revision_conflict"));
    }
    let profile:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'version',version) FROM candidate_profiles WHERE singleton_key='primary'").fetch_optional(&mut **tx).await.map_err(db)?;
    let confirmation = get(tx, "phase1_profile_confirmation").await?;
    if input["policy"]["enabled"] == true
        && (!confirmed(profile.as_ref(), confirmation.as_ref())
            || profile
                .as_ref()
                .is_none_or(|p| p["version"] != input["policy"]["profile_version"]))
    {
        return Err(Failure("current_confirmed_profile_version_required"));
    }
    if let Some(mut work) = get(tx, "apply_profile_sync:naukri").await? {
        if work["status"] == "executing" && work["operation"] == "sync_profile" {
            return Err(Failure("profile_sync_in_progress_reconcile_before_change"));
        }
        work["status"] = json!("idle");
        work["lease_token"] = Value::Null;
        work["lease_until"] = Value::Null;
        work["revision"] = json!(next(&work)?);
        work["next_at"] = Value::Null;
        put(tx, "apply_profile_sync:naukri", &work).await?;
    }
    let mut policy = input["policy"].clone();
    if policy["verify_saved_resume"] == false {
        policy
            .as_object_mut()
            .ok_or_else(invalid)?
            .remove("verify_saved_resume");
    }
    let value = json!({"revision":next(&current)?,"policy":policy});
    put(tx, "naukri_profile_sync_policy", &value).await?;
    Ok(value)
}
