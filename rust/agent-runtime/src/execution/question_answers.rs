//! Factual owner-answer validation. An answer grants no browser action or personal fact edit.
use super::storage::*;
use crate::{Failure, Result, legacy_regex::Regex};
use chrono::{DateTime, NaiveDate, NaiveDateTime, TimeZone, Utc};
use serde_json::Value;
use std::sync::LazyLock;
pub fn field_answer<'a>(question: &Value, answer: &'a str) -> &'a str {
    if question["answer_type"] == "availability"
        && question["options"]
            .as_array()
            .is_some_and(|a| !a.is_empty())
    {
        answer.split_once(" | ").map_or(answer, |(value, _)| value)
    } else {
        answer
    }
}
pub fn validate(question: &Value, answer: &str, now: DateTime<Utc>) -> Result<String> {
    let text = question["question"].as_str().ok_or_else(invalid)?;
    crate::missing_contract::permitted(text, answer)?;
    let value = field_answer(question, answer);
    let maximum = question["max_characters"]
        .as_u64()
        .filter(|n| *n > 0 && *n <= 4000)
        .ok_or_else(invalid)? as usize;
    if value
        .trim_matches(crate::context_contract::python_space)
        .is_empty()
        || value.chars().count() > maximum
    {
        return Err(Failure("answer_length_invalid"));
    }
    match question["form_kind"].as_str() {
        Some("number") => {
            static NUMBER: LazyLock<Regex> =
                LazyLock::new(|| Regex::new(r"\A-?[0-9]+(?:\.[0-9]+)?\z", false));
            if !NUMBER.is_match(value)? {
                return Err(Failure("numeric_answer_required"));
            }
        }
        Some("date" | "month") => {
            let month = question["form_kind"] == "month";
            let valid = if month {
                value.len() == 7
                    && NaiveDate::parse_from_str(&format!("{value}-01"), "%Y-%m-%d").is_ok()
            } else {
                value.len() == 10 && NaiveDate::parse_from_str(value, "%Y-%m-%d").is_ok()
            };
            if !valid
                || !value.bytes().enumerate().all(|(i, b)| {
                    if i == 4 || !month && i == 7 {
                        b == b'-'
                    } else {
                        b.is_ascii_digit()
                    }
                })
                || value.starts_with("0000")
            {
                return Err(Failure("iso_date_answer_required"));
            }
        }
        Some("email") => {
            static EMAIL: LazyLock<Regex> =
                LazyLock::new(|| Regex::new(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\z", false));
            if !EMAIL.is_match(value)? {
                return Err(Failure("email_answer_required"));
            }
        }
        Some("url") if crate::resources::public_https(value).is_none() => {
            return Err(Failure("public_https_answer_required"));
        }
        _ => {}
    }
    let options = question["options"].as_array().ok_or_else(invalid)?;
    if !options.is_empty() && !options.iter().any(|o| o == value) {
        return Err(Failure("answer_must_match_option"));
    }
    let folded = automated_apply_domain::text::folded(answer);
    if question["answer_type"] == "choice"
        && options.is_empty()
        && !matches!(folded.as_str(), "yes" | "no")
    {
        return Err(Failure("yes_or_no_required"));
    }
    if question["answer_type"] == "availability" {
        if !options.is_empty()
            && automated_apply_domain::text::folded(value) == "no"
            && answer == value
        {
            return Ok(stamp(now + chrono::Duration::days(7)));
        }
        let slot = if options.is_empty() {
            answer
        } else {
            answer.split_once(" | ").map_or("", |(_, slot)| slot)
        };
        let mut parts = slot
            .split(crate::context_contract::python_space)
            .filter(|s| !s.is_empty());
        let rejected = || Failure("availability_requires_future_datetime_and_iana_timezone");
        let local = parts.next().ok_or_else(rejected)?;
        let zone = parts.next().ok_or_else(rejected)?;
        if parts.next().is_some() || local.len() != 16 {
            return Err(rejected());
        }
        static STAMP: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\z", false));
        if !STAMP.is_match(local)? || local.starts_with("0000") {
            return Err(rejected());
        }
        let local =
            NaiveDateTime::parse_from_str(local, "%Y-%m-%dT%H:%M").map_err(|_| rejected())?;
        let zone = zone.parse::<chrono_tz::Tz>().map_err(|_| rejected())?;
        let scheduled = zone
            .from_local_datetime(&local)
            .single()
            .ok_or_else(rejected)?
            .with_timezone(&Utc);
        if scheduled <= now || scheduled > now + chrono::Duration::days(90) {
            return Err(rejected());
        }
        return Ok(stamp(scheduled.min(now + chrono::Duration::days(7))));
    }
    static SHORT: LazyLock<Regex> = LazyLock::new(|| Regex::new("salary|relocat|authoriz", true));
    Ok(stamp(
        now + chrono::Duration::days(if SHORT.is_match(text)? { 7 } else { 30 }),
    ))
}
