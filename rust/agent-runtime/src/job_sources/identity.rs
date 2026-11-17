//! Exact source/board/URL and conservative content identity. Similarity never merges jobs.
use crate::{Failure, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
use uuid::Uuid;
fn invalid() -> Failure {
    Failure("invalid_public_job_identity")
}
fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
pub fn folded(value: Option<&str>) -> String {
    static TAGS: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"<[^>]*>").unwrap());
    let plain = TAGS.replace_all(value.unwrap_or(""), " ");
    automated_apply_domain::text::folded(&plain)
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
pub fn observation_key(item: &Value) -> Result<String> {
    let key = if let Some(id) = item["source_job_id"].as_str().filter(|s| !s.is_empty()) {
        let board = match item["data_provenance"].get("board_token") {
            None => "",
            Some(Value::String(s)) if s.len() <= 208 => s,
            _ => return Err(invalid()),
        };
        format!("id:{board}:{id}")
    } else {
        format!(
            "url:{}",
            crate::job_urls::canonical(item["original_url"].as_str().ok_or_else(invalid)?)
                .map_err(|_| invalid())?
        )
    };
    Ok(digest(&key))
}
pub fn content_identity(item: &Value, company: Option<Uuid>) -> Result<Option<String>> {
    let Some(company) = company.filter(|id| !id.is_nil()) else {
        return Ok(None);
    };
    if item["company_domain"].as_str().is_none_or(|s| s.is_empty())
        || item["location"].as_str().is_none_or(|s| s.is_empty())
        || item["remote_type"] == "unknown"
    {
        return Ok(None);
    }
    let description = folded(item["description"].as_str());
    if description.chars().count() < 200 {
        return Ok(None);
    }
    let title = folded(item["title"].as_str());
    let location = folded(item["location"].as_str());
    let remote = item["remote_type"]
        .as_str()
        .filter(|s| matches!(*s, "remote" | "hybrid" | "onsite"))
        .ok_or_else(invalid)?;
    if title.is_empty() {
        return Err(invalid());
    }
    Ok(Some(digest(&format!(
        "{company}|{title}|{location}|{remote}|{description}"
    ))))
}
