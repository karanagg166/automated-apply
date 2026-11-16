//! Pure selected-mailbox rules; neither subject nor body keywords confirm an application.
use super::*;
use chrono::{Duration, Months};
use regex::Regex;
use std::sync::LazyLock;
pub struct Window {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}
fn at(value: &Value) -> Result<DateTime<Utc>> {
    crate::gmail_history::contract::timestamp(value)
        .map(|at| at.with_timezone(&Utc))
        .ok_or_else(invalid)
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
pub fn window(policy: &Value, state: &Value, now: DateTime<Utc>) -> Result<Window> {
    let end = if state["window_end"].is_null() {
        now
    } else {
        at(&state["window_end"])?
    };
    let historical = if let Some(months) = policy["history_months"].as_u64() {
        end.checked_sub_months(Months::new(months.try_into().map_err(|_| invalid())?))
            .ok_or_else(invalid)?
    } else {
        end.checked_sub_signed(Duration::days(
            policy["backfill_days"].as_i64().ok_or_else(invalid)?,
        ))
        .ok_or_else(invalid)?
    };
    let start = if !state["window_start"].is_null() {
        at(&state["window_start"])?
    } else if !state["checkpoint"].is_null() {
        std::cmp::max(historical, at(&state["checkpoint"])? - Duration::minutes(5))
    } else {
        historical
    };
    if start > end || end > now {
        return Err(invalid());
    }
    Ok(Window { start, end })
}
pub fn request(
    policy: &Value,
    state: &Value,
    window: &Window,
) -> Result<(Vec<String>, Option<String>, Option<String>)> {
    let folders = policy["folders"].as_array().ok_or_else(invalid)?;
    let index = state
        .get("folder_index")
        .map(|v| v.as_u64().ok_or_else(invalid))
        .transpose()?
        .unwrap_or(0) as usize;
    if !folders.is_empty() && index >= folders.len() {
        return Err(invalid());
    }
    let mut labels = policy["label_allowlist"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    let folder = folders
        .get(index)
        .and_then(Value::as_str)
        .map(str::to_owned);
    if let Some(folder) = &folder {
        labels.push(folder.clone());
    }
    let query = if policy["read_body"] == true {
        let mut query = format!(
            "after:{} before:{}",
            window.start.timestamp(),
            window.end.timestamp() + 1
        );
        let senders = policy["sender_allowlist"].as_array().ok_or_else(invalid)?;
        if !senders.is_empty() {
            query.push_str(" {");
            query.push_str(
                &senders
                    .iter()
                    .map(|v| v.as_str().map(|s| format!("from:{s}")).ok_or_else(invalid))
                    .collect::<Result<Vec<_>>>()?
                    .join(" "),
            );
            query.push('}');
        }
        if let Some(extra) = policy["query_allowlist"].as_str() {
            query.push_str(&format!(" ({extra})"));
        }
        Some(query)
    } else {
        None
    };
    Ok((labels, query, folder))
}
pub fn advance(
    policy: &Value,
    state: &mut Value,
    next: Option<&str>,
    window: &Window,
) -> Result<bool> {
    if next.is_some_and(|s| s.len() > 2048 || state["page_token"].as_str() == Some(s)) {
        return Err(Failure("gmail_page_token_invalid"));
    }
    state["page_token"] = next.map(|s| json!(s)).unwrap_or(Value::Null);
    if next.is_some_and(|s| !s.is_empty()) {
        return Ok(true);
    }
    let folders = policy["folders"].as_array().ok_or_else(invalid)?;
    let index = state
        .get("folder_index")
        .map(|v| v.as_u64().ok_or_else(invalid))
        .transpose()?
        .unwrap_or(0) as usize;
    if !folders.is_empty() && index + 1 < folders.len() {
        state["folder_index"] = json!(index + 1);
    } else {
        state["checkpoint"] = json!(stamp(window.end));
        state["window_start"] = Value::Null;
        state["window_end"] = Value::Null;
        state["folder_index"] = json!(0);
    }
    Ok(false)
}
pub struct Selected {
    pub received: DateTime<Utc>,
    pub subject: String,
    pub sender: String,
    pub thread: String,
    pub evidence: Value,
}
pub fn metadata(
    message: &Value,
    message_id: &str,
    policy: &Value,
    window: &Window,
    folder: Option<&str>,
) -> Result<Option<Selected>> {
    static TOPIC: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)\b(?:job|jobs|applied|applying|application|resume|candidature|interview|hiring|vacancy|career|recruit(?:er|ing|ment)?|position|follow[ -]?up)\b").unwrap()
    });
    if message["id"] != message_id {
        return Err(Failure("gmail_message_identity_mismatch"));
    }
    let invalid = || Failure("gmail_message_metadata_invalid");
    let millis = match &message["internalDate"] {
        Value::String(s) => s.parse::<i64>().ok(),
        Value::Number(n) => n.as_i64(),
        _ => None,
    }
    .ok_or_else(invalid)?;
    let received = DateTime::from_timestamp_millis(millis).ok_or_else(invalid)?;
    let headers = message["payload"]["headers"]
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?;
    let mut names = HashMap::new();
    for header in headers {
        let name = header["name"].as_str().ok_or_else(invalid)?;
        let name = automated_apply_domain::text::folded(name);
        let value = header["value"].as_str().ok_or_else(invalid)?;
        if matches!(name.as_str(), "from" | "subject") && names.contains_key(&name) {
            return Err(invalid());
        }
        names.insert(name, value.to_owned());
    }
    let subject = names.get("subject").cloned().unwrap_or_default();
    if subject.chars().count() > 4000 {
        return Err(invalid());
    }
    let sender = if let Some(raw) = names.get("from") {
        crate::mail_evidence::single_address(raw).ok_or_else(invalid)?
    } else {
        String::new()
    };
    if received < window.start || received > window.end || !TOPIC.is_match(&subject) {
        return Ok(None);
    }
    let senders = policy["sender_allowlist"].as_array().ok_or_else(invalid)?;
    if !senders.is_empty()
        && !senders.iter().any(|v| {
            v.as_str()
                .is_some_and(|s| automated_apply_domain::text::folded(s) == sender)
        })
    {
        return Ok(None);
    }
    let empty = Vec::new();
    let labels = message
        .get("labelIds")
        .map(|v| v.as_array().ok_or_else(invalid))
        .transpose()?
        .unwrap_or(&empty);
    if !policy["label_allowlist"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .all(|v| labels.contains(v))
        || folder.is_some_and(|s| !labels.contains(&json!(s)))
    {
        return Ok(None);
    }
    let mut signals = Vec::new();
    if !policy["folders"].as_array().ok_or_else(invalid)?.is_empty() {
        static SIGNALS: LazyLock<Vec<(&str, Regex)>> = LazyLock::new(|| {
            [
            (
                "possible_acknowledgment",
                r"(?i)\b(?:application (?:received|confirmation)|received your application|thank you for applying)\b",
            ),
            ("possible_interview", r"(?i)\binterview\b"),
            (
                "possible_rejection",
                r"(?i)\b(?:rejection|not moving forward|application unsuccessful)\b",
            ),
            (
                "possible_recruiter_response",
                r"(?i)\b(?:recruiter|recruiting|talent acquisition)\b",
            ),
            (
                "possible_status_update",
                r"(?i)\b(?:application (?:status|update)|under review|next steps)\b",
            ),
        ].into_iter().map(|(name,pattern)|(name,Regex::new(pattern).unwrap())).collect()
        });
        for (name, pattern) in SIGNALS.iter() {
            if pattern.is_match(&subject) {
                signals.push(*name);
            }
        }
    }
    let thread = message["threadId"]
        .as_str()
        .ok_or(Failure("gmail_thread_id_invalid"))?;
    crate::mailboxes::message_id(thread).map_err(|_| Failure("gmail_thread_id_invalid"))?;
    let evidence = json!({"links":[],"signals":signals,"verification_status":"requires_review","submission_confirmed":false,"status_confirmed":false,"signal_basis":if policy["folders"].as_array().unwrap().is_empty(){"metadata_only_no_status_inference"}else{"selected_subject_keywords_uncertain"}});
    Ok(Some(Selected {
        received,
        subject,
        sender,
        thread: thread.to_owned(),
        evidence,
    }))
}
