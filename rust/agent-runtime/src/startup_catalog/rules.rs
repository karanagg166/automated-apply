//! Actual explicit query filters. Ranges and relevance do not establish factual headcounts.
use crate::{Failure, Result};
use automated_apply_domain::text::folded;
use serde_json::Value;
pub fn band(value: &str) -> Option<(i64, Option<i64>)> {
    match value {
        "1-10" => Some((1, Some(10))),
        "2-10" => Some((2, Some(10))),
        "11-50" => Some((11, Some(50))),
        "51-200" => Some((51, Some(200))),
        "201-500" => Some((201, Some(500))),
        "500+" => Some((501, None)),
        _ => None,
    }
}
pub fn size_band(count: Option<i64>) -> Result<&'static str> {
    match count {
        None => Ok("unknown"),
        Some(1..=10) => Ok("1-10"),
        Some(11..=50) => Ok("11-50"),
        Some(51..=200) => Ok("51-200"),
        Some(201..=500) => Ok("201-500"),
        Some(501..) => Ok("500+"),
        _ => Err(Failure("invalid_startup_size_record")),
    }
}
pub fn size_allowed(size: &Value, filters: &Value) -> Result<bool> {
    let count = if size["employee_count"].is_null() {
        None
    } else {
        Some(
            size["employee_count"]
                .as_i64()
                .filter(|n| *n >= 1 && *n <= 10000000)
                .ok_or(Failure("invalid_startup_size_record"))?,
        )
    };
    if filters["exact_employee_count"] == true && count.is_none() {
        return Ok(false);
    }
    let name = size["team_size_band"]
        .as_str()
        .ok_or(Failure("invalid_startup_size_record"))?;
    let range = band(name);
    if name != "unknown" && range.is_none() {
        return Err(Failure("invalid_startup_size_record"));
    }
    if let Some(min) = filters["min_employees"].as_i64() {
        if count.or(range.map(|r| r.0)).is_none_or(|n| n < min) {
            return Ok(false);
        }
    }
    if name == "unknown" {
        return Ok(filters["include_unknown_size"] == true);
    }
    let allowed = filters["size_bands"]
        .as_array()
        .ok_or(Failure("invalid_startup_contract"))?;
    if !allowed.is_empty() && !allowed.iter().any(|v| v == name) {
        return Ok(false);
    }
    if let Some(max) = filters["max_employees"].as_i64() {
        return Ok(count.or(range.and_then(|r| r.1)).is_some_and(|n| n <= max));
    }
    Ok(true)
}
pub fn role_allowed(title: &str, roles: &[String]) -> bool {
    let title = folded(title);
    roles.is_empty() || roles.iter().any(|s| title.contains(&folded(s)))
}
pub fn location_allowed(locations: &[String], remotes: &[String], filters: &Value) -> Result<bool> {
    let policy = filters["remote_preference"].as_str();
    let requested = filters["locations"]
        .as_array()
        .ok_or(Failure("invalid_startup_contract"))?;
    let remote = policy == Some("remote") && remotes.iter().any(|s| s == "remote");
    let matching = requested.iter().any(|loc| {
        loc.as_str().is_some_and(|loc| {
            locations
                .iter()
                .any(|value| folded(value).contains(&folded(loc)))
        })
    });
    if !requested.is_empty() && !remote && !matching {
        return Ok(false);
    }
    Ok(matches!(policy, None | Some("any")) || remotes.iter().any(|s| Some(s.as_str()) == policy))
}
pub fn industry_allowed(industry: Option<&str>, requested: &[String]) -> bool {
    let value = folded(industry.unwrap_or(""));
    requested.is_empty()
        || requested.iter().any(|item| {
            let normalized = folded(item);
            let terms: Vec<&str> = match normalized.as_str() {
                "ai" => vec!["ai", "artificial intelligence"],
                "saas" => vec!["saas", "software as a service"],
                "fintech" => vec!["fintech", "financial technology"],
                "developer tools" => vec!["developer tools", "developer tooling", "devtools"],
                _ => vec![normalized.as_str()],
            };
            terms.iter().any(|term| {
                value
                    .match_indices(*term)
                    .any(|(at, _)| crate::evidence_retrieval::bounded(&value, at, at + term.len()))
            })
        })
}
