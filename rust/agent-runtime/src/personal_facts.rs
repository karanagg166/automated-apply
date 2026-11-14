//! Exact saved compensation/location/authorization facts. No salary/visa guesses or conversions.
use crate::{Failure, Result, link_resolver::normalize};
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use std::sync::LazyLock;
#[derive(Debug, Serialize)]
pub struct Answer {
    pub handled: bool,
    pub answer: Option<String>,
    pub field: Option<&'static str>,
    pub category: &'static str,
}
fn result(answer: Option<String>, field: &'static str, category: &'static str) -> Answer {
    Answer {
        handled: true,
        answer,
        field: Some(field),
        category,
    }
}
fn unknown(field: &'static str, category: &'static str) -> Answer {
    result(None, field, category)
}
/// Decimal arithmetic is string based. Profile constraints have already bounded the amount.
fn amount(value: &Value, shift: i64) -> Result<String> {
    let text = match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => return Err(Failure("invalid_compensation_fact")),
    };
    let negative = text.starts_with('-');
    let text = text.trim_start_matches(['-', '+']);
    let (mantissa, exponent) = text.split_once(['e', 'E']).unwrap_or((text, "0"));
    let fraction = mantissa.split_once('.').map(|(_, f)| f.len()).unwrap_or(0);
    let digits = mantissa.replace('.', "");
    if !digits.bytes().all(|b| b.is_ascii_digit()) || digits.is_empty() {
        return Err(Failure("invalid_compensation_fact"));
    }
    let leading = digits.len() - digits.trim_start_matches('0').len();
    if leading == digits.len() {
        return Ok(if negative { "-0" } else { "0" }.into());
    }
    let exponent = exponent
        .parse::<i64>()
        .map_err(|_| Failure("invalid_compensation_fact"))?;
    let point = (digits.len() as i64)
        .checked_sub(fraction as i64)
        .and_then(|n| n.checked_add(exponent))
        .and_then(|n| n.checked_sub(leading as i64))
        .and_then(|n| n.checked_sub(shift))
        .filter(|n| (-64..=64).contains(n))
        .ok_or(Failure("invalid_compensation_fact"))?;
    let digits = digits[leading..].trim_end_matches('0');
    let value = if point <= 0 {
        format!("0.{}{}", "0".repeat((-point) as usize), digits)
    } else if point as usize >= digits.len() {
        format!("{}{}", digits, "0".repeat(point as usize - digits.len()))
    } else {
        format!(
            "{}.{}",
            &digits[..point as usize],
            &digits[point as usize..]
        )
    };
    Ok(if negative { format!("-{value}") } else { value })
}
fn phrase(text: &str, needle: &str) -> bool {
    if needle.is_empty() {
        return !text.is_empty();
    }
    format!(" {text} ").contains(&format!(" {needle} "))
}
fn yes_no(value: &Value) -> Option<String> {
    value.as_bool().map(|v| if v { "Yes" } else { "No" }.into())
}
pub fn resolve(profile: &Value, question: &str, category: &str) -> Result<Answer> {
    let prefs = &profile["preferences"];
    let q = normalize(question);
    static PREFIX: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^(?:(?:what is|what are|please provide|please specify|please enter|provide|enter) )?(?:your )?").unwrap()
    });
    let simple = PREFIX.replace(&q, "");
    static MONEY: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^(current|present|expected|desired) (?:(annual|yearly|monthly|hourly) )?(ctc|salary|compensation)(?: (?:in )?(inr|usd|eur|gbp|lpa))?$").unwrap()
    });
    if let Some(parts) = MONEY.captures(&simple) {
        let field = if matches!(&parts[1], "current" | "present") {
            "current_compensation"
        } else {
            "expected_compensation"
        };
        let value = &prefs[field];
        if value.is_null() {
            return Ok(unknown(field, "compensation"));
        }
        let expected = parts.get(2).map(|v| match v.as_str() {
            "annual" | "yearly" => "year",
            "monthly" => "month",
            _ => "hour",
        });
        let kind = &parts[3];
        let unit = parts.get(4).map(|v| v.as_str());
        if expected.is_some_and(|p| value["period"] != p)
            || (kind == "ctc" && value["kind"] != "ctc")
            || (kind == "salary" && value["kind"] != "base_salary")
            || unit.is_some_and(|u| u != "lpa" && value["currency"] != u.to_ascii_uppercase())
        {
            return Ok(unknown(field, "compensation"));
        }
        let answer = if unit == Some("lpa") {
            if value["currency"] == "INR" && value["period"] == "year" {
                Some(amount(&value["amount"], 5)?)
            } else {
                None
            }
        } else {
            let currency = value["currency"]
                .as_str()
                .ok_or(Failure("invalid_compensation_fact"))?;
            let period = value["period"]
                .as_str()
                .ok_or(Failure("invalid_compensation_fact"))?;
            let kind = value["kind"]
                .as_str()
                .ok_or(Failure("invalid_compensation_fact"))?
                .replace('_', " ");
            Some(format!(
                "{} {currency} per {period} ({kind})",
                amount(&value["amount"], 0)?
            ))
        };
        return Ok(result(answer, field, "compensation"));
    }
    static DATE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^(?:when can you start|when are you available(?: to start)?|available from|availability date|earliest start date|start date|availability)$").unwrap()
    });
    if DATE.is_match(&simple) {
        return Ok(result(
            prefs["availability_date"].as_str().map(Into::into),
            "availability_date",
            "personal_details",
        ));
    }
    static LOCATION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^(?:current location|current city|city of residence)$").unwrap()
    });
    if LOCATION.is_match(&simple) {
        return Ok(result(
            prefs["current_location"].as_str().map(Into::into),
            "current_location",
            "personal_details",
        ));
    }
    static RELOCATE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"^(?:are you |would you be )?(?:willing|open) to (?:relocate|relocation)(?: to .+)?$",
        )
        .unwrap()
    });
    static TARGET: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?:relocate|relocation) to (.+)$").unwrap());
    if RELOCATE.is_match(&simple) {
        let answer = if let Some(target) = TARGET.captures(&simple) {
            prefs["relocation_locations"]
                .as_array()
                .is_some_and(|rows| {
                    rows.iter()
                        .filter_map(Value::as_str)
                        .any(|v| normalize(v) == target[1])
                })
                .then(|| "Yes".into())
        } else {
            yes_no(&prefs["open_to_relocation"])
        };
        return Ok(result(answer, "open_to_relocation", "personal_details"));
    }
    if category == "work_authorization" || q.contains("eligible to work") {
        let empty = Vec::new();
        let rows = prefs["work_authorizations"].as_array().unwrap_or(&empty);
        let matches: Vec<_> = rows
            .iter()
            .filter(|row| {
                let name = row["country_name"]
                    .as_str()
                    .map(normalize)
                    .unwrap_or_default();
                let code = row["country_code"]
                    .as_str()
                    .unwrap_or("")
                    .to_ascii_lowercase();
                phrase(&q, &name)
                    || phrase(&q, &format!("in {code}"))
                    || phrase(&q, &format!("in the {code}"))
            })
            .collect();
        if matches.len() != 1 {
            return Ok(unknown("work_authorizations", "work_authorization"));
        }
        let row = matches[0];
        let name = normalize(row["country_name"].as_str().unwrap_or(""));
        let code = row["country_code"]
            .as_str()
            .unwrap_or("")
            .to_ascii_lowercase();
        let country = format!("(?:{}|{})", regex::escape(&name), regex::escape(&code));
        let sponsorship=Regex::new(&format!(r"^(?:do you require|will you require|will you now or in (?:the )?future require) (?:visa )?sponsorship (?:to work )?in (?:the )?{country}$")).map_err(|_|Failure("invalid_authorization_fact"))?;
        let authorized=Regex::new(&format!(r"^(?:are you |are you legally |are you currently )?(?:legally )?(?:authorized|authorised|eligible) to work in (?:the )?{country}$")).map_err(|_|Failure("invalid_authorization_fact"))?;
        let answer = if sponsorship.is_match(&q) {
            yes_no(&row["requires_sponsorship_now_or_future"])
        } else if authorized.is_match(&q) {
            yes_no(&row["authorized_to_work"])
        } else {
            None
        };
        return Ok(result(answer, "work_authorizations", "work_authorization"));
    }
    Ok(Answer {
        handled: false,
        answer: None,
        field: None,
        category: "personal_details",
    })
}
