//! Small evidence-only public adapter rules. No network IO or private facts are inferred.
use crate::{Failure, Result};
use chrono::DateTime;
use serde_json::{Value, json};
use std::sync::LazyLock;
fn invalid() -> Failure {
    Failure("public_job_record_invalid")
}
pub fn remote_policy(text: Option<&str>) -> &'static str {
    let text = text.unwrap_or("").to_lowercase();
    if ["no remote", "not remote", "onsite only", "on-site only"]
        .iter()
        .any(|s| text.contains(s))
    {
        "onsite"
    } else if text.contains("hybrid") {
        "hybrid"
    } else if text.contains("remote") {
        "remote"
    } else if text.contains("onsite") || text.contains("on-site") {
        "onsite"
    } else {
        "unknown"
    }
}
pub fn employment(text: Option<&str>) -> Option<&'static str> {
    let text = text.unwrap_or("").to_lowercase().replace(['-', ' '], "_");
    ["full_time", "part_time", "contract", "internship"]
        .into_iter()
        .find(|word| text.contains(word))
}
pub fn date(value: &Value) -> Result<Value> {
    if value.is_null() || value == "" {
        return Ok(Value::Null);
    }
    let at = if let Some(number) = value
        .as_f64()
        .or_else(|| value.as_bool().map(|v| if v { 1.0 } else { 0.0 }))
    {
        if !number.is_finite() || !(-62135596800.0..=253402300799.0).contains(&number) {
            return Err(invalid());
        }
        let micros = (number * 1_000_000.0).round_ties_even() as i64;
        DateTime::from_timestamp_micros(micros).ok_or_else(invalid)?
    } else if let Some(text) = value.as_str() {
        // Provider ISO evidence is distinct from DTO numeric timestamp coercion.
        if !text.starts_with(|c: char| c.is_ascii_digit())
            || text.chars().all(|c| c.is_ascii_digit()) && text.len() != 8
        {
            return Err(invalid());
        }
        let text = if text.len() == 8 && text.is_ascii() && text.chars().all(|c| c.is_ascii_digit())
        {
            format!("{}-{}-{}", &text[..4], &text[4..6], &text[6..])
        } else {
            text.to_owned()
        };
        let raw = crate::packet_record::timestamp(&json!(text), true).map_err(|_| invalid())?;
        crate::packet_record::expiry(&raw)
            .map_err(|_| invalid())?
            .ok_or_else(invalid)?
    } else {
        return Err(invalid());
    };
    Ok(json!(at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        true
    )))
}
pub fn structured_salary(
    minimum: &Value,
    maximum: &Value,
    currency: &Value,
    interval: &Value,
    periods: &[(&str, &str)],
) -> Value {
    if [minimum, maximum].iter().any(|v| {
        !v.is_null()
            && !v
                .as_f64()
                .is_some_and(|n| n.is_finite() && (0.0..=1e12).contains(&n))
    }) || minimum.is_null() && maximum.is_null()
    {
        return json!({});
    }
    if minimum
        .as_f64()
        .zip(maximum.as_f64())
        .is_some_and(|(a, b)| a > b)
    {
        return json!({});
    }
    let Some(currency) = currency
        .as_str()
        .filter(|s| s.len() == 3 && s.bytes().all(|b| b.is_ascii_uppercase()))
    else {
        return json!({});
    };
    let Some(period) = interval
        .as_str()
        .and_then(|s| periods.iter().find(|(key, _)| *key == s))
        .map(|(_, period)| *period)
    else {
        return json!({});
    };
    json!({"salary_min":minimum,"salary_max":maximum,"salary_currency":currency,"salary_period":period})
}
pub fn salary_fields(raw: Option<&str>) -> Result<Value> {
    let Some(raw) = raw.filter(|s| !s.is_empty()) else {
        return Ok(json!({}));
    };
    if raw.len() > 16384 {
        return Err(invalid());
    }
    let text = raw.to_lowercase();
    let currency = ["USD", "INR", "EUR", "GBP", "CAD", "AUD"]
        .into_iter()
        .find(|c| text.contains(&c.to_lowercase()))
        .or(if raw.contains('€') {
            Some("EUR")
        } else if raw.contains('£') {
            Some("GBP")
        } else {
            None
        });
    static PERIODS: LazyLock<Vec<(&str, crate::legacy_regex::Regex)>> = LazyLock::new(|| {
        vec![
            (
                "year",
                crate::legacy_regex::Regex::new(r"\byear|annual|p\.a\.|\bpa\b", false),
            ),
            ("month", crate::legacy_regex::Regex::new(r"\bmonth", false)),
            (
                "hour",
                crate::legacy_regex::Regex::new(r"\bhour|/hr\b", false),
            ),
            ("week", crate::legacy_regex::Regex::new(r"\bweek", false)),
            ("day", crate::legacy_regex::Regex::new(r"\bday", false)),
        ]
    });
    let mut period = None;
    for (name, pattern) in PERIODS.iter() {
        if pattern.is_match(&text)? {
            period = Some(*name);
            break;
        }
    }
    static SALARY: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?(?:\s*[-–—]\s*(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?)?").unwrap()
    });
    let compatible = raw
        .chars()
        .map(|c| {
            if ('\u{001c}'..='\u{001f}').contains(&c) {
                '\t'
            } else {
                c
            }
        })
        .collect::<String>();
    let Some(c) = SALARY.captures(&compatible) else {
        return Ok(json!({}));
    };
    let number = |n: &str, unit: Option<&str>| -> Result<f64> {
        let digits = n
            .chars()
            .filter(|c| *c != ',')
            .map(|c| {
                crate::profile_contract::decimal_digit(c)
                    .and_then(|n| char::from_digit(n, 10))
                    .unwrap_or(c)
            })
            .collect::<String>();
        let number = digits.parse::<f64>().map_err(|_| invalid())?
            * match unit.unwrap_or("").to_ascii_lowercase().as_str() {
                "k" => 1000.0,
                "m" => 1000000.0,
                _ => 1.0,
            };
        if !number.is_finite() {
            return Err(invalid());
        }
        Ok(number)
    };
    let minimum = number(
        c.get(1).expect("required salary").as_str(),
        c.get(2).map(|m| m.as_str()),
    )?;
    let maximum = c
        .get(3)
        .map(|m| number(m.as_str(), c.get(4).map(|m| m.as_str())))
        .transpose()?;
    if maximum.is_some_and(|max| minimum > max) {
        return Ok(json!({}));
    }
    Ok(
        json!({"salary_min":minimum,"salary_max":maximum,"salary_currency":currency,"salary_period":period}),
    )
}
fn equal_identifier(a: &str, b: &str) -> bool {
    fn folded(s: &str) -> String {
        s.chars()
            .map(|c| match c {
                'İ' | 'ı' => 'i',
                'ſ' => 's',
                'K' => 'k',
                c => c.to_ascii_lowercase(),
            })
            .collect()
    }
    folded(a) == folded(b)
}
fn parts<'a>(raw: &'a str, host: &str) -> Result<(&'a str, &'a str)> {
    if raw.len() > 2048 {
        return Err(invalid());
    }
    let (scheme, rest) = raw.split_once("://").ok_or_else(invalid)?;
    if !scheme.eq_ignore_ascii_case("https") {
        return Err(invalid());
    }
    let at = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    if &rest[..at] != host {
        return Err(invalid());
    }
    let rest = &rest[at..];
    let (rest, fragment) = rest.split_once('#').unwrap_or((rest, ""));
    if !fragment.is_empty() {
        return Err(invalid());
    }
    let (path, query) = rest.split_once('?').unwrap_or((rest, ""));
    Ok((path, query))
}
pub fn hosted_url(
    raw: &str,
    board: &str,
    source: &str,
    region: &str,
    application: bool,
) -> Result<String> {
    let host = match source {
        "lever" if region == "eu" => "jobs.eu.lever.co",
        "lever" => "jobs.lever.co",
        "ashby" => "jobs.ashbyhq.com",
        _ => return Err(invalid()),
    };
    let (path, query) = parts(raw, host)?;
    if !query.is_empty() {
        return Err(invalid());
    }
    let path = path.strip_suffix('/').unwrap_or(path);
    let mut segments = path.strip_prefix('/').ok_or_else(invalid)?.split('/');
    let actual = segments.next().ok_or_else(invalid)?;
    let id = segments.next().ok_or_else(invalid)?;
    let suffix = segments.next();
    if !equal_identifier(actual, board)
        || id.is_empty()
        || id.len() > 100
        || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        || segments.next().is_some()
    {
        return Err(invalid());
    }
    if suffix.is_some_and(|s| {
        !application
            || s != if source == "lever" {
                "apply"
            } else {
                "application"
            }
    }) {
        return Err(invalid());
    }
    Ok(raw.into())
}
pub fn smart_url(raw: &str, board: &str, id: &str) -> Result<String> {
    let (path, query) = parts(raw, "jobs.smartrecruiters.com")?;
    if !matches!(query, "" | "oga=true") {
        return Err(invalid());
    }
    let path = path.strip_suffix('/').unwrap_or(path);
    let (actual, posting) = path
        .strip_prefix('/')
        .and_then(|s| s.split_once('/'))
        .ok_or_else(invalid)?;
    if !equal_identifier(actual, board) {
        return Err(invalid());
    }
    let prefix = posting.get(..id.len()).ok_or_else(invalid)?;
    if !equal_identifier(prefix, id) {
        return Err(invalid());
    }
    let suffix = &posting[id.len()..];
    if !suffix.is_empty()
        && !suffix.strip_prefix('-').is_some_and(|s| {
            !s.is_empty()
                && s.chars().all(|c| {
                    c.is_ascii_alphanumeric()
                        || matches!(c, '_' | '%' | '~' | '-' | 'İ' | 'ı' | 'ſ' | 'K')
                })
        })
    {
        return Err(invalid());
    }
    Ok(raw.into())
}
