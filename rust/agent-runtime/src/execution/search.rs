//! Bounded ordinary UI discovery scheduling. Query text is never candidate experience or fit.
use super::{
    contracts::{self, Kind},
    preflight, queue_control,
    storage::*,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::sync::LazyLock;
use uuid::Uuid;
pub const WORK: &str = "apply_search:naukri";
fn queries(setting: &Value, profile: &Value) -> Result<Vec<(String, bool)>> {
    let roles = if setting["preferences_mode"] == "custom" {
        &setting["preferences"]["roles"]
    } else {
        &profile["preferences"]["target_titles"]
    };
    if roles.is_null() {
        return Ok(vec![]);
    }
    let roles = roles.as_array().ok_or_else(invalid)?;
    if roles.len() > 100 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let fresher = profile["verified_experience_years"]
        .as_f64()
        .is_some_and(|n| n.is_finite() && (0.0..1.0).contains(&n));
    static INTERNSHIP: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?i)\b(intern|internship|trainee)\b").expect("fixed role expression")
    });
    let mut values = vec![];
    for role in roles {
        let role = role
            .as_str()
            .filter(|s| s.chars().count() <= 255)
            .ok_or_else(invalid)?;
        if fresher {
            for query in [(role.to_owned(), true), (role.to_owned(), false)] {
                if !values.contains(&query) {
                    values.push(query);
                }
            }
            if !INTERNSHIP.is_match(role) {
                let query = (format!("{role} Intern"), true);
                if !values.contains(&query) {
                    values.push(query);
                }
            }
        } else {
            values.push((role.to_owned(), false));
        }
    }
    Ok(values)
}
fn quote(value: &str) -> String {
    let mut result = String::new();
    for b in value.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-' | b'~') {
            result.push(char::from(b));
        } else {
            result.push_str(&format!("%{b:02X}"));
        }
    }
    result
}
fn url(query: &(String, bool), page: i64) -> Option<String> {
    let lower = query.0.to_lowercase();
    let mut slug = String::new();
    let mut separator = false;
    for c in lower.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            if separator && !slug.is_empty() {
                slug.push('-');
            }
            slug.push(c);
            separator = false;
        } else {
            separator = true;
        }
    }
    if slug.is_empty() {
        return None;
    }
    let mut url = format!("https://www.naukri.com/{slug}-jobs");
    if page > 1 {
        url.push_str(&format!("-{page}"));
    }
    if query.1 {
        url.push_str(&format!(
            "?k={}&experience=0&nignbevent_src=jobsearchDeskGNB",
            quote(
                query
                    .0
                    .trim_matches(crate::context_contract::python_space)
                    .to_lowercase()
                    .as_str()
            )
        ));
    }
    Some(url)
}
/// Pure deterministic part, also used by the final actual-Python search oracle.
pub fn proposal(
    old: &Value,
    setting: &Value,
    profile: &Value,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    if !setting["sources"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .any(|s| s == "naukri_ui_search")
    {
        return Ok(None);
    }
    for key in ["lease_until", "next_at"] {
        if !old[key].is_null() && timestamp(&old[key])? > now {
            return Ok(None);
        }
    }
    let queries = queries(setting, profile)?;
    if queries.is_empty() {
        return Ok(None);
    }
    let mut index = old
        .get("role_index")
        .map(|v| v.as_i64().ok_or_else(invalid))
        .transpose()?
        .unwrap_or(0)
        .rem_euclid(queries.len() as i64) as usize;
    let mut page = 1;
    let previous = (index + queries.len() - 1) % queries.len();
    let previous_page = old.get("search_page").and_then(Value::as_i64).unwrap_or(1);
    if (1..3).contains(&previous_page)
        && !queries[previous].1
        && old["status"] == "idle"
        && old["last_finished_at"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
        && old["last_error"].is_null()
        && old["last_cycle_count"] == 0
        && url(&queries[previous], previous_page).is_some_and(|s| old["url"] == s)
    {
        index = previous;
        page = previous_page + 1;
    }
    let Some(url) = url(&queries[index], page) else {
        return Ok(None);
    };
    let count = old
        .get("candidates_found")
        .map(|v| v.as_i64().filter(|n| *n >= 0).ok_or_else(invalid))
        .transpose()?
        .unwrap_or(0);
    Ok(Some(
        json!({"url":url,"role_index":index+1,"search_page":page,"candidates_found":count}),
    ))
}
pub(crate) async fn work_in(
    tx: &mut Transaction<'_, Postgres>,
    binding: &Value,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let config = queue_control::configuration(tx).await?;
    let setting = &config["policy"]["platforms"]["naukri"];
    if config["state"] != "RUNNING" || setting["enabled"] != true {
        return Ok(None);
    }
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if execution["mode"] == "OFF"
        || super::local_policy::preference_in(tx, "naukri").await? == "disabled"
    {
        return Ok(None);
    }
    // Scheduling/authority reads do not require loading private candidate resources.
    let old = get(tx, WORK).await?.unwrap_or(json!({"revision":0}));
    for key in ["lease_until", "next_at"] {
        if !old[key].is_null() && timestamp(&old[key])? > now {
            return Ok(None);
        }
    }
    let profile = match preflight::profile_in(tx, &json!({})).await {
        Ok(p) => p,
        Err(Failure("verified_profile_context_changed")) => return Ok(None),
        Err(e) => return Err(e),
    };
    let Some(proposal) = proposal(&old, setting, &profile, now)? else {
        return Ok(None);
    };
    let interval = setting["discovery_interval_seconds"]
        .as_i64()
        .ok_or_else(invalid)?;
    let value = json!({"id":Uuid::new_v5(&Uuid::NAMESPACE_URL,WORK.as_bytes()),"revision":next(&old)?,"lease_token":Uuid::new_v4(),"lease_until":stamp(now+chrono::Duration::seconds(180)),"operation":"search_jobs","url":proposal["url"],"status":"leased","binding":binding,"policy_revision":config["revision"],"role_index":proposal["role_index"],"search_page":proposal["search_page"],"last_started_at":stamp(now),"next_at":stamp(now+chrono::Duration::seconds(interval)),"candidates_found":proposal["candidates_found"],"last_error":null});
    put(tx, WORK, &value).await?;
    Ok(Some(value))
}
pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    report: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    if report["kind"] == "source_candidates" {
        if report["observed_url"] != work["url"] {
            return Err(Failure("queue_document_identity_changed"));
        }
        let urls: Vec<String> =
            serde_json::from_value(report["candidates"].clone()).map_err(|_| invalid())?;
        let added = super::intake::batch_in(tx, &urls, "naukri_ui_search", now).await?;
        let total = work["candidates_found"]
            .as_i64()
            .filter(|n| *n >= 0)
            .and_then(|n| n.checked_add(added as i64))
            .ok_or_else(invalid)?;
        work["candidates_found"] = json!(total);
        work["last_cycle_count"] = json!(added);
        work["last_error"] = Value::Null;
    } else if matches!(report["kind"].as_str(), Some("needs_input" | "failed")) {
        work["last_error"] = report
            .get("reason")
            .filter(|v| v.is_string())
            .cloned()
            .unwrap_or(json!("source_observation_unavailable"));
    } else {
        return Err(Failure("background_report_not_supported"));
    }
    work["status"] = json!("idle");
    work["last_finished_at"] = json!(stamp(now));
    Ok(())
}
/// Host-internal scheduling only; native caller must authenticate the current binding first.
pub async fn work(c: &mut sqlx::PgConnection, binding: &Value) -> Result<Option<Value>> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        work_in(&mut tx, binding, now).await
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
