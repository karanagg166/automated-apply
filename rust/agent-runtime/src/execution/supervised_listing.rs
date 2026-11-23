//! Local operator control for one supervised Naukri listing that shows 100+ applicants.
use super::{
    automatic, budgets, contracts, events, filters, intake, preflight, queue, queue_control,
    storage::*,
};
use crate::{Failure, Result, browser_inventory::Browser, configuration::Configuration};
use chrono::{DateTime, Duration, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, Postgres, Transaction};
use std::{borrow::Cow, path::Path};

const SCOPE: &str = "supervised_100_plus";

pub(super) fn scoped(config: &Value) -> bool {
    config.get(SCOPE).is_some()
}

pub(super) fn clear(config: &mut Value) -> Result<()> {
    config.as_object_mut().ok_or_else(invalid)?.remove(SCOPE);
    Ok(())
}

pub(super) fn permits_work(config: &Value, work: &Value, at: DateTime<Utc>) -> bool {
    !scoped(config)
        || (config["state"] == "RUNNING"
            && config["policy"]["platforms"]["naukri"]["mode"] == "SUPERVISED"
            && work["platform"] == "naukri"
            && work["id"].is_string()
            && work["id"] == config[SCOPE]["work_id"]
            && timestamp(&config[SCOPE]["expires_at"]).is_ok_and(|expires| at < expires))
}

pub(super) fn allows_applicants(work: &Value) -> bool {
    work["facts"]["applicants_min"] == 100 && work["facts"]["applicants_max"].is_null()
}

pub(super) fn require_write(config: &Value, work: &Value, at: DateTime<Utc>) -> Result<()> {
    if scoped(config) && !(permits_work(config, work, at) && allows_applicants(work)) {
        return Err(Failure("supervised_listing_scope_mismatch"));
    }
    Ok(())
}

pub(super) fn policy_for_work<'a>(
    config: &'a Value,
    work: &Value,
    at: DateTime<Utc>,
) -> Result<Cow<'a, Value>> {
    let policy = &config["policy"];
    if !scoped(config) || !permits_work(config, work, at) || !allows_applicants(work) {
        return Ok(Cow::Borrowed(policy));
    }
    let limits = contracts::limits(policy, "naukri")?;
    if limits["applicant_limit"] != 1000 || limits["unknown_applicants"] != "needs_review" {
        return Err(Failure("supervised_listing_applicant_rule_changed"));
    }
    let mut policy = policy.clone();
    let setting = &mut policy["platforms"]["naukri"];
    setting["applicants_mode"] = json!("custom");
    setting["limits"]["applicant_limit"] = limits["applicant_limit"].clone();
    setting["limits"]["unknown_applicants"] = json!("allow_lower_bound");
    Ok(Cow::Owned(policy))
}

pub async fn start(config: &Path, revision: i64, listing: &str) -> Result<()> {
    let config = Configuration::load(config)?;
    if config.browser != Browser::Brave
        || !config.browser_profiles.native_enabled
        || !config.browser_profiles.commands_enabled
    {
        return Err(Failure("brave_native_runtime_required"));
    }
    let mut connection = config.connect(false).await?;
    crate::server::readiness(&mut connection, &config).await?;
    let mut tx = connection.begin().await.map_err(db)?;
    lock(&mut tx).await?;
    let result = match start_in(&mut tx, revision, listing).await {
        Ok(saved) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            saved
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            return Err(error);
        }
    };
    println!("{result}");
    Ok(())
}

async fn start_in(
    tx: &mut Transaction<'_, Postgres>,
    revision: i64,
    listing: &str,
) -> Result<Value> {
    let at = now(tx).await?;
    let mut config = queue_control::configuration(tx).await?;
    if config["revision"] != revision {
        return Err(Failure("queue_policy_revision_conflict"));
    }
    let setting = &config["policy"]["platforms"]["naukri"];
    let limits = contracts::limits(&config["policy"], "naukri")?;
    if scoped(&config)
        || config["state"] != "STOPPED"
        || setting["mode"] != "SUPERVISED"
        || setting["enabled"] != true
        || setting["owner_submission_authorized"] != true
        || setting["hourly_submission_cap"] != 1
        || limits["applicant_limit"] != 1000
        || limits["unknown_applicants"] != "needs_review"
        || config["policy"]["platforms"]
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .any(|(name, policy)| name != "naukri" && policy["enabled"] == true)
        || crate::lifecycle::control(tx).await?.mode != crate::lifecycle::Mode::Stopped
        || get(tx, "naukri_automation")
            .await?
            .is_some_and(|legacy| legacy["state"] != "STOPPED")
    {
        return Err(Failure("stopped_supervised_listing_policy_required"));
    }
    queue_control::require_start(tx, &config, at).await?;
    let totals = budgets::totals_in(tx, "naukri", at).await?;
    let cap = setting["supervised_submission_cap"]
        .as_i64()
        .ok_or_else(invalid)?;
    if totals["lifetime_apply"] != cap - 1 || totals["hourly_work"] != 0 {
        return Err(Failure("one_supervised_listing_allowance_required"));
    }

    let account = automatic::account(tx).await?;
    let selection = get(tx, "chr_selection").await?.unwrap_or(Value::Null);
    let pin = get(tx, "chr_fixed_profile").await?.unwrap_or(Value::Null);
    let binding = selection["profile_binding_id"]
        .as_str()
        .ok_or_else(invalid)?;
    let profile = get(tx, &format!("chr_prof:{binding}"))
        .await?
        .unwrap_or(Value::Null);
    if account["profile_binding_id"] != binding
        || pin["profile_binding_id"] != binding
        || pin["browser"] != "brave"
        || pin["verified_via"] != "owner_reviewed_dedicated_brave_profile"
        || profile["id"] != binding
        || profile["commands_enabled"] != true
        || crate::browser_profiles::public(&profile, &json!(binding), at)?["status"] != "CONNECTED"
    {
        return Err(Failure("current_supervised_brave_binding_required"));
    }

    let url = filters::naukri_url(listing)?;
    let requisition = url.rsplit('-').next().ok_or_else(invalid)?;
    if intake::protected_in(tx, &[requisition.to_owned()])
        .await?
        .contains(requisition)
    {
        return Err(Failure("prior_application_or_unknown_submission_no_replay"));
    }
    let mut work = queue::enqueue_in(tx, &url, "naukri_ui_search", None, at).await?;
    if work["url"] != url
        || !matches!(
            work["stage"].as_str(),
            Some("DISCOVERED" | "NEEDS_INPUT" | "PAUSED")
        )
        || !matches!(work["status"].as_str(), Some("waiting" | "queued"))
        || work["admitted_actions"] != json!([])
        || !work["packet_id"].is_null()
        || !work["lease_until"].is_null()
        || work["form_pending"] == true
        || !setting["sources"]
            .as_array()
            .ok_or_else(invalid)?
            .contains(&work["source"])
    {
        return Err(Failure("untouched_supervised_listing_required"));
    }
    let current_profile = preflight::profile_in(tx, &work).await?;
    if current_profile["id"] != account["candidate_profile_id"] {
        return Err(Failure("naukri_account_binding_context_changed"));
    }
    let work_id = work["id"].as_str().ok_or_else(invalid)?.to_owned();
    let deadline = now(tx).await? + Duration::minutes(15);
    let revision = next(&config)?;
    config["revision"] = json!(revision);
    config["state"] = json!("RUNNING");
    config[SCOPE] = json!({"work_id":work_id,"expires_at":stamp(deadline)});
    work["revision"] = json!(next(&work)?);
    work["policy_revision"] = json!(revision);
    work["stage"] = json!("DISCOVERED");
    work["status"] = json!("queued");
    work["operation"] = json!("inspect_job");
    work["available_at"] = json!(stamp(at));
    work["updated_at"] = json!(stamp(at));
    work["reason"] = Value::Null;
    work["profile_version"] = Value::Null;
    put(tx, "application_queue_policy", &config).await?;
    put(tx, &format!("apply_work:{work_id}"), &work).await?;
    events::queue(tx, &work, "supervised_100_plus_listing_started", at).await?;
    Ok(
        json!({"state":config["state"],"revision":revision,"scope":config[SCOPE],"application_dispatched":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exception_is_bound_to_exact_work_evidence_and_deadline() {
        let at = DateTime::parse_from_rfc3339("2026-11-24T03:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let deadline = at + Duration::minutes(15);
        let mut config = json!({
            "state":"RUNNING",
            "policy":{"platforms":{"naukri":{
                "mode":"SUPERVISED", "applicants_mode":"global", "age_mode":"global", "cap_mode":"global"
            }},"global_limits":{
                "applicant_limit":1000,"unknown_applicants":"needs_review",
                "daily_cap":4,"max_job_age_days":14,"minimum_match_score":50
            }},
            SCOPE:{"work_id":"fixture-work","expires_at":stamp(deadline)}
        });
        let mut work = json!({
            "id":"fixture-work","platform":"naukri",
            "facts":{"applicants_min":100,"applicants_max":null,"posted_at":stamp(at - Duration::days(2))}
        });
        let temporary = policy_for_work(&config, &work, at).unwrap();
        let temporary = contracts::limits(&temporary, "naukri").unwrap();
        assert_eq!(temporary["unknown_applicants"], "allow_lower_bound");
        assert_eq!(temporary["applicant_limit"], 1000);
        assert_eq!(temporary["max_job_age_days"], 14);
        assert_eq!(temporary["minimum_match_score"], 50);
        assert_eq!(
            filters::listing_exclusion(&work["facts"], &temporary, at).unwrap(),
            None
        );
        assert_eq!(
            config["policy"]["global_limits"]["unknown_applicants"],
            "needs_review"
        );
        work["facts"]["posted_at"] = json!(stamp(at - Duration::days(15)));
        assert_eq!(
            filters::listing_exclusion(&work["facts"], &temporary, at).unwrap(),
            Some("posting_outside_age_limit")
        );
        assert!(require_write(&config, &work, at).is_ok());
        assert!(require_write(&config, &work, deadline).is_err());
        for value in [json!(null), json!(10), json!(1000)] {
            work["facts"]["applicants_min"] = value;
            assert_eq!(
                policy_for_work(&config, &work, at).unwrap().as_ref(),
                &config["policy"]
            );
            assert!(require_write(&config, &work, at).is_err());
        }
        work["facts"]["applicants_min"] = json!(100);
        work["facts"]["applicants_max"] = json!(100);
        assert!(require_write(&config, &work, at).is_err());
        work["facts"]["applicants_max"] = Value::Null;
        work["id"] = json!("unrelated-work");
        assert!(!permits_work(&config, &work, at));
        assert!(require_write(&config, &work, at).is_err());
        clear(&mut config).unwrap();
        assert_eq!(
            contracts::limits(&policy_for_work(&config, &work, at).unwrap(), "naukri").unwrap()["unknown_applicants"],
            "needs_review"
        );
    }
}
