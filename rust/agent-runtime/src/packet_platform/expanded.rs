//! Destination identity checks for the expanded platform packet adapters.
use super::{Destination, Selection, posting_unavailable, public_https};
use crate::{
    Result,
    public_discovery::{self, Platform},
};
use chrono::{DateTime, Utc};
use reqwest::Url;
use serde_json::Value;

pub(super) const SOURCES: &[&str] = &[
    "instahyre",
    "wellfound",
    "work_at_a_startup",
    "internshala",
    "hiringcafe",
    "himalayas",
    "we_work_remotely",
];

fn ascii_id(value: &str, min: usize, max: usize) -> bool {
    (min..=max).contains(&value.len()) && value.bytes().all(|b| b.is_ascii_alphanumeric())
}
fn number(value: &str) -> bool {
    !value.is_empty() && value.len() <= 20 && value.bytes().all(|b| b.is_ascii_digit())
}
fn slug(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 255
        && percent_encoding::percent_decode_str(value)
            .decode_utf8()
            .is_ok_and(|decoded| {
                decoded
                    .chars()
                    .all(|ch| ch.is_alphanumeric() || matches!(ch, '-' | '_'))
            })
}
fn numbered_slug(value: &str) -> Option<&str> {
    if let Some((id, slug_part)) = value.split_once('-') {
        return (number(id) && slug(slug_part)).then_some(id);
    }
    number(value).then_some(value)
}
fn portal_host(platform: &str, host: &str) -> bool {
    let bare = host.strip_prefix("www.").unwrap_or(host);
    match platform {
        "instahyre" => bare == "instahyre.com",
        "wellfound" => bare == "wellfound.com",
        "work_at_a_startup" => bare == "workatastartup.com",
        "internshala" => bare == "internshala.com",
        "hiringcafe" => matches!(bare, "hiringcafe.com" | "hiring.cafe"),
        _ => false,
    }
}

fn exact_https(raw: &str) -> Option<Url> {
    if raw.chars().any(|ch| ch.is_control() || ch.is_whitespace()) || raw.contains('\\') {
        return None;
    }
    Url::parse(&public_https(raw)?).ok()
}

// Numeric portal IDs survive slug changes. Internshala's listing type and full slug are its key.
fn identity(platform: &str, url: &Url) -> Option<String> {
    if !portal_host(platform, url.host_str()?) {
        return None;
    }
    let path = url.path().strip_prefix('/')?;
    let path = path.strip_suffix('/').unwrap_or(path);
    let parts: Vec<_> = path.split('/').collect();
    match (platform, parts.as_slice()) {
        ("instahyre", [name]) => numbered_slug(name.strip_prefix("job-")?).map(str::to_owned),
        ("instahyre", ["job", id]) if number(id) => Some((*id).into()),
        ("instahyre", ["job", id, title]) if number(id) && slug(title) => Some((*id).into()),
        ("wellfound", ["jobs", listing]) => numbered_slug(listing).map(str::to_owned),
        ("work_at_a_startup", ["jobs", id]) if number(id) => Some((*id).into()),
        ("internshala", [kind @ ("job" | "internship"), "detail", listing]) if slug(listing) => {
            Some(format!("{kind}/{listing}"))
        }
        ("hiringcafe", ["job", id]) if ascii_id(id, 16, 16) => Some((*id).into()),
        _ => None,
    }
}

fn portal_destination(
    platform: &str,
    job: &Value,
    observations: &[(String, String)],
) -> (Option<String>, bool) {
    let Some(mut posting) = job["job_url"].as_str().and_then(exact_https) else {
        return (None, false);
    };
    let Some(posting_id) = identity(platform, &posting) else {
        return (None, false);
    };
    let meta_source = &job["discovery_metadata"]["source_name"];
    if !meta_source.is_null() && meta_source != platform {
        return (None, false);
    }
    let observed = job["source_verification_status"] == "observed"
        && observations.iter().any(|(source, url)| {
            source == platform
                && exact_https(url)
                    .and_then(|url| identity(platform, &url))
                    .as_ref()
                    == Some(&posting_id)
        });
    let reported = matches!(
        job["source_verification_status"].as_str(),
        Some("source_reported" | "verified")
    );
    if !observed && !reported {
        return (None, true);
    }
    if !job["application_url"].is_null()
        && job["application_url"]
            .as_str()
            .is_none_or(|url| !url.trim().is_empty())
    {
        let Some(application) = job["application_url"].as_str().and_then(exact_https) else {
            return (None, true);
        };
        if application
            .host_str()
            .is_some_and(|host| portal_host(platform, host))
            && identity(platform, &application).as_ref() != Some(&posting_id)
        {
            return (None, false);
        }
    }
    // Portal handoff starts on its reviewed listing. Canonical listing navigation carries no action parameters.
    posting.set_query(None);
    posting.set_fragment(None);
    (Some(posting.into()), true)
}

fn feed_destination(
    platform: Platform,
    job: &Value,
    observations: &[(String, String)],
) -> (Option<String>, bool) {
    let name = platform.name();
    let metadata = &job["discovery_metadata"];
    let Some(raw) = job["application_url"].as_str() else {
        return (None, false);
    };
    let identity_matches = job["job_url"].as_str().is_some_and(|canonical| {
        public_discovery::source_url(platform, raw).is_ok_and(|value| value == canonical)
    }) && exact_https(raw).is_some()
        && metadata["source_name"] == name
        && metadata["original_url"] == raw
        && metadata["source_job_id"]
            .as_str()
            .is_some_and(|id| !id.is_empty() && id.chars().count() <= 255)
        && observations
            .iter()
            .any(|(platform, url)| platform == name && url == raw);
    let ready = identity_matches && job["source_verification_status"] == "source_reported";
    (ready.then(|| raw.to_owned()), identity_matches)
}

pub(super) fn select(
    platform: &'static str,
    job: &Value,
    observations: &[(String, String)],
    now: DateTime<Utc>,
) -> Result<Selection> {
    let (destination, consistent) = match Platform::parse(platform) {
        Ok(feed) => feed_destination(feed, job, observations),
        Err(_) => portal_destination(platform, job, observations),
    };
    let expiry = &job["discovery_metadata"]["expires_at"];
    let expired = !expiry.is_null()
        && expiry
            .as_str()
            .and_then(|value| DateTime::parse_from_rfc3339(value).ok())
            .is_none_or(|time| time.to_utc() <= now);
    let unavailable = expired
        || posting_unavailable(job, now.date_naive())?
        || matches!(
            job["status"].as_str(),
            Some("applied" | "submitted" | "rejected")
        )
        || job["discovery_metadata"]["data_provenance"]["posting_status"] == "already_applied";
    let destination = destination.filter(|_| !unavailable);
    let valid = destination.is_some();
    let mut warnings = vec![
        "Confirm the vacancy and employer on the provider's listing before applying.".to_owned(),
    ];
    if !consistent {
        warnings.push("Review the saved platform, posting identity and source observation.".into());
    }
    if unavailable {
        warnings.push("The saved listing is closed, expired or already acted on.".into());
    }
    Ok(Selection {
        platform: Some(platform),
        preparation_supported: true,
        destination: Destination {
            application_url: destination,
            kind: if valid {
                "employer_external"
            } else if unavailable {
                "expired_or_invalid"
            } else {
                "unknown"
            },
            valid,
            source_confidence: if consistent {
                "source_consistent"
            } else {
                "source_conflict"
            },
            warnings,
        },
    })
}
