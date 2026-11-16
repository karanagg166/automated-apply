//! Saved evidence determines size/hiring. Relevance, absent jobs and future claims prove none.
use super::rules;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::collections::{BTreeSet, HashSet};
fn invalid() -> Failure {
    Failure("invalid_startup_intelligence_record")
}
fn bound(rows: &[Value], max: usize) -> Result<()> {
    if rows.len() > max
        || rows
            .iter()
            .any(|v| !v.is_object() || v.to_string().len() > 2097152)
        || rows.iter().map(|v| v.to_string().len()).sum::<usize>() > 16 * 1024 * 1024
    {
        return Err(Failure("startup_intelligence_inventory_limit"));
    }
    Ok(())
}
fn time(value: &Value) -> Result<DateTime<Utc>> {
    if !value.is_string() {
        return Err(invalid());
    }
    let normalized = crate::packet_record::timestamp(value, true).map_err(|_| invalid())?;
    DateTime::parse_from_rfc3339(normalized.as_str().ok_or_else(invalid)?)
        .map(|d| d.to_utc())
        .map_err(|_| invalid())
}
fn stamp(at: DateTime<Utc>) -> String {
    at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        false,
    )
}
fn text<'a>(v: &'a Value, max: usize) -> Result<&'a str> {
    v.as_str().filter(|s| s.len() <= max).ok_or_else(invalid)
}
fn current(at: DateTime<Utc>, now: DateTime<Utc>, days: i64) -> bool {
    at <= now && at >= now - chrono::Duration::days(days)
}
fn verified(v: &Value) -> bool {
    matches!(v.as_str(), Some("source_reported" | "human_confirmed"))
}
fn size_count(v: &Value) -> Result<Option<i64>> {
    if v.is_null() {
        Ok(None)
    } else {
        v.as_i64()
            .filter(|n| (1..=10000000).contains(n))
            .map(Some)
            .ok_or_else(invalid)
    }
}
fn optional_text(v: &Value, max: usize) -> Result<Value> {
    if !v.is_null() {
        text(v, max)?;
    }
    Ok(v.clone())
}
pub fn company_size(observations: &[Value], now: DateTime<Utc>, days: i64) -> Result<Value> {
    if !(1..=3650).contains(&days) {
        return Err(invalid());
    }
    bound(observations, 1000)?;
    let mut eligible = Vec::new();
    let mut evidence = Vec::new();
    for o in observations {
        let at = time(&o["observed_at"])?;
        let attrs = o["attributes"].as_object().ok_or_else(invalid)?;
        if attrs.get("historical").is_some_and(|v| !v.is_boolean()) {
            return Err(invalid());
        }
        let name = attrs
            .get("team_size_band")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        if name != "unknown" && rules::band(name).is_none() {
            return Err(invalid());
        }
        if name != "unknown" {
            let count = size_count(&o["attributes"]["employee_count"])?;
            if evidence.len() < 20 {
                let mut item = json!({"source":text(&o["source"],100)?,"source_url":text(&o["source_url"],2048)?,"observed_at":stamp(at),"historical":attrs.get("historical").cloned().unwrap_or(json!(false)),"employee_count":count,"band":name,"verification_status":text(&o["verification_status"],50)?});
                if at > now {
                    item["future_observation_requires_review"] = json!(true);
                }
                evidence.push(item);
            }
            if !crate::contacts::rules::truthy(&o["attributes"]["historical"])
                && current(at, now, days)
                && verified(&o["verification_status"])
            {
                eligible.push((o, at));
            }
        }
    }
    if eligible
        .iter()
        .any(|(o, _)| o["verification_status"] == "human_confirmed")
    {
        eligible.retain(|(o, _)| o["verification_status"] == "human_confirmed");
    }
    eligible.sort_by(|(a, at), (b, bt)| {
        bt.cmp(at)
            .then_with(|| b["id"].as_str().cmp(&a["id"].as_str()))
    });
    let mut seen = HashSet::new();
    let mut candidates = Vec::new();
    for (o, _) in eligible {
        let source = text(&o["source"], 100)?;
        let identity = text(&o["identity_key"], 100)?;
        if seen.insert((source, identity)) {
            candidates.push(o);
        }
    }
    let mut counts = BTreeSet::new();
    let mut lower = 0;
    let mut upper = 10000000;
    for o in &candidates {
        let (low, high) =
            rules::band(text(&o["attributes"]["team_size_band"], 20)?).ok_or_else(invalid)?;
        lower = lower.max(low);
        upper = upper.min(high.unwrap_or(10000000));
        if let Some(count) = size_count(&o["attributes"]["employee_count"])? {
            counts.insert(count);
        }
    }
    let conflict =
        counts.len() > 1 || lower > upper || counts.iter().any(|c| *c < lower || *c > upper);
    let chosen = if conflict {
        None
    } else {
        candidates
            .iter()
            .find(|o| !o["attributes"]["employee_count"].is_null())
            .copied()
            .or_else(|| candidates.first().copied())
    };
    Ok(
        json!({"employee_count":chosen.map(|o|o["attributes"]["employee_count"].clone()).unwrap_or(Value::Null),"team_size_band":chosen.map(|o|o["attributes"]["team_size_band"].clone()).unwrap_or(json!("unknown")),"team_size_evidence_status":if conflict{json!("conflicting")}else{chosen.map(|o|o["verification_status"].clone()).unwrap_or(json!("team_size_unknown"))},"team_size_evidence":evidence}),
    )
}
pub fn hiring(
    jobs: &[Value],
    observations: &[Value],
    job_observations: &[Value],
    now: DateTime<Utc>,
    days: i64,
) -> Result<Value> {
    if !(1..=365).contains(&days) {
        return Err(invalid());
    }
    bound(jobs, 500)?;
    bound(observations, 1000)?;
    bound(job_observations, 2000)?;
    let mut signals = Vec::new();
    for job in jobs {
        let meta = if job["discovery_metadata"].is_null() {
            json!({})
        } else {
            job["discovery_metadata"].clone()
        };
        if !meta.is_object() {
            return Err(invalid());
        }
        let at = if job["last_observed_at"].is_null() {
            None
        } else {
            Some(time(&job["last_observed_at"])?)
        };
        let mut fresh = at.is_some_and(|at| current(at, now, days));
        let expiry = if crate::contacts::rules::truthy(&meta["date_expires"]) {
            &meta["date_expires"]
        } else {
            &meta["expires_at"]
        };
        if crate::contacts::rules::truthy(expiry) {
            fresh &= time(expiry).is_ok_and(|at| at > now);
        }
        if crate::contacts::rules::truthy(&meta["is_expired"]) || meta["listing_status"] == "closed"
        {
            fresh = false;
        }
        let mut board = false;
        for o in job_observations.iter().filter(|o| {
            o["job_id"] == job["id"]
                && o["source"] == "greenhouse"
                && o["verification_status"] == "source_reported"
        }) {
            if current(time(&o["last_observed_at"])?, now, days) {
                board = true;
                break;
            }
        }
        let confirmed = fresh
            && (board
                || meta["is_confirmed_current"] == true
                    && job["source_verification_status"] == "source_reported");
        let posted = if job["date_posted"].is_null() {
            Value::Null
        } else {
            json!(stamp(time(&job["date_posted"])?))
        };
        signals.push(json!({"job_id":text(&job["id"],100)?,"title":text(&job["title"],255)?,"source":text(&job["source_platform"],100)?,"evidence_url":text(&job["job_url"],2048)?,"posted_at":posted,"observed_at":at.map(stamp),"fresh":fresh,"hiring_status":if confirmed{"hiring_confirmed"}else if fresh{"hiring_possible"}else{"hiring_unknown"},"location":optional_text(&job["location"],255)?,"remote_policy":optional_text(&job["remote_type"],50)?,"verification_status":optional_text(&job["source_verification_status"],50)?}));
    }
    let mut statements = Vec::new();
    for o in observations {
        if !o["attributes"].is_object() {
            return Err(invalid());
        }
        let attrs = &o["attributes"];
        let at = time(&o["observed_at"])?;
        let statement = attrs["hiring_statement"].as_str();
        if !crate::contacts::rules::truthy(&attrs["historical"])
            && current(at, now, days)
            && verified(&o["verification_status"])
            && matches!(statement, Some("hiring_possible" | "not_currently_hiring"))
            && (statement != Some("not_currently_hiring")
                || attrs["authoritative_statement"] == true)
        {
            statements.push((o, at));
        }
    }
    let mut latest = None;
    for entry in &statements {
        if latest.is_none_or(|prior: &(&Value, DateTime<Utc>)| entry.1 > prior.1) {
            latest = Some(entry);
        }
    }
    let status = if signals
        .iter()
        .any(|s| s["hiring_status"] == "hiring_confirmed")
    {
        json!("hiring_confirmed")
    } else if signals.iter().any(|s| s["fresh"] == true) {
        json!("hiring_possible")
    } else {
        latest
            .map(|(o, _)| o["attributes"]["hiring_statement"].clone())
            .unwrap_or(json!("hiring_unknown"))
    };
    let evidence=statements.iter().take(20).map(|(o,at)|Ok(json!({"source":text(&o["source"],100)?,"evidence_url":text(&o["source_url"],2048)?,"observed_at":stamp(*at),"status":o["attributes"]["hiring_statement"]}))).collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"hiring_status":status,"hiring_evidence":signals,"hiring_statement_evidence":evidence}),
    )
}
