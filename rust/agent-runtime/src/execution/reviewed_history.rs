//! Retained owner-reviewed mailbox history; no mailbox read or inferred application status.
use super::storage::*;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::{Postgres, Transaction};
pub(crate) async fn load_in(
    tx: &mut Transaction<'_, Postgres>,
    now: DateTime<Utc>,
) -> Result<Vec<Value>> {
    let rows:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN bytes<=262144 AND sum(bytes) OVER()<=8388608 THEN value ELSE NULL END FROM (SELECT key,value,octet_length(value::text) AS bytes FROM owner_preferences WHERE starts_with(key,'gmail_application:') ORDER BY key LIMIT 5001) bounded ORDER BY key").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 5000 {
        return Err(Failure("gmail_history_limit_reached"));
    }
    let rows = rows
        .into_iter()
        .map(|v| v.ok_or(Failure("gmail_history_limit_reached")))
        .collect::<Result<Vec<_>>>()?;
    if rows.iter().map(|v| v.to_string().len()).sum::<usize>() > 8 * 1024 * 1024 {
        return Err(Failure("gmail_history_limit_reached"));
    }
    rows.into_iter()
        .filter_map(|row| {
            if row["deleted"] == true {
                return None;
            }
            match timestamp(&row["expires_at"]) {
                Ok(at) if at > now => Some(
                    if row["confirmed_application"].as_bool().is_none()
                        || row["company"].as_str().is_none()
                        || row["role"].as_str().is_none()
                        || (!row["job_url"].is_null() && row["job_url"].as_str().is_none())
                    {
                        Err(invalid())
                    } else {
                        Ok(row)
                    },
                ),
                Ok(_) => None,
                Err(error) => Some(Err(error)),
            }
        })
        .collect()
}
pub fn previously_applied(job: &Value, company: Option<&Value>, history: &[Value]) -> bool {
    let fold = |raw: &str| {
        automated_apply_domain::text::folded(
            raw.trim_matches(crate::context_contract::python_space),
        )
    };
    let name = company
        .and_then(|c| c["name"].as_str())
        .map(fold)
        .unwrap_or_default();
    let urls = ["job_url", "application_url"]
        .into_iter()
        .filter_map(|k| job[k].as_str())
        .filter_map(|raw| {
            crate::job_urls::ats(Some(raw))
                .ok()
                .flatten()
                .or_else(|| crate::job_urls::canonical(raw).ok())
        })
        .collect::<std::collections::HashSet<_>>();
    history.iter().any(|row| {
        row["confirmed_application"] == true
            && (row["job_url"]
                .as_str()
                .is_some_and(|raw| urls.contains(raw))
                || (row["job_url"].as_str().is_none_or(str::is_empty) || urls.is_empty())
                    && !name.is_empty()
                    && row["company"].as_str().is_some_and(|s| fold(s) == name)
                    && row["role"].as_str().is_some_and(|s| {
                        fold(s) == job["title"].as_str().map(fold).unwrap_or_default()
                    }))
    })
}
