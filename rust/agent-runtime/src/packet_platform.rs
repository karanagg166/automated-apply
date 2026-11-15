//! Saved destination preparation only. Recognizing an ATS grants no browser or submission rights.
use crate::{Failure, Result, resources::public_https};
use automated_apply_domain::text::{folded, lowered};
use chrono::NaiveDate;
use regex::Regex;
use serde::Serialize;
use serde_json::{Value, json};
use std::sync::LazyLock;

#[derive(Default)]
pub struct Policy {
    pub testing: bool,
    pub origins: Vec<String>,
}
#[derive(Serialize)]
pub struct Destination {
    pub application_url: Option<String>,
    pub kind: &'static str,
    pub valid: bool,
    pub source_confidence: &'static str,
    pub warnings: Vec<String>,
}
#[derive(Serialize)]
pub struct Selection {
    pub platform: Option<&'static str>,
    pub preparation_supported: bool,
    pub destination: Destination,
}
const SOURCES: &[&str] = &[
    "manual_browser",
    "naukri",
    "owner_extension",
    "greenhouse",
    "remotive",
    "arbeitnow",
    "hacker_news",
    "lever",
    "ashby",
    "smartrecruiters",
];
pub fn capabilities() -> Value {
    json!(SOURCES.iter().map(|p|json!({"platform":p,"job_discovery":"configured_source_dependent","application_preparation":"supported","resume_selection":"supported","screening_answer_generation":"supported","browser_autofill":if matches!(*p,"manual_browser"|"naukri") {"assisted_native_fields"} else {"not_implemented"},"automated_submission":"not_authorized_or_verified","manual_handoff":"supported","submission_mode":"manual_handoff","live_verified":false})).collect::<Vec<_>>())
}
fn text<'a>(job: &'a Value, key: &str) -> Result<&'a str> {
    job[key]
        .as_str()
        .ok_or(Failure("invalid_packet_job_record"))
}
fn host(url: &str) -> Option<String> {
    reqwest::Url::parse(url).ok()?.host_str().map(String::from)
}
fn naukri(url: &str) -> bool {
    host(url).is_some_and(|h| h == "naukri.com" || h.ends_with(".naukri.com"))
}
fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
fn iso_date(value: &str) -> Option<NaiveDate> {
    if value.starts_with("0000") || value.trim() != value {
        return None;
    }
    let parsed = match value.len() {
        10 => NaiveDate::parse_from_str(value, "%Y-%m-%d")
            .or_else(|_| NaiveDate::parse_from_str(value, "%G-W%V-%u")),
        8 => NaiveDate::parse_from_str(value, "%Y%m%d")
            .or_else(|_| NaiveDate::parse_from_str(value, "%GW%V%u"))
            .or_else(|_| NaiveDate::parse_from_str(&format!("{value}-1"), "%G-W%V-%u")),
        7 => NaiveDate::parse_from_str(&format!("{value}1"), "%GW%V%u"),
        _ => return None,
    };
    parsed.ok()
}
pub fn posting_unavailable(job: &Value, today: NaiveDate) -> Result<bool> {
    let metadata = &job["discovery_metadata"];
    if !metadata.is_null() && !metadata.is_object() {
        return Err(Failure("invalid_packet_job_record"));
    }
    let evidence = &metadata["data_provenance"];
    if !evidence.is_null() && !evidence.is_object() {
        return Err(Failure("invalid_packet_job_record"));
    }
    if matches!(job["status"].as_str(), Some("archived" | "closed"))
        || matches!(
            job["source_verification_status"].as_str(),
            Some("expired" | "invalid" | "closed")
        )
        || evidence["posting_status"] == "closed"
    {
        return Ok(true);
    }
    let expiry = &evidence["valid_through"];
    Ok(truth(expiry) && expiry.as_str().and_then(iso_date).is_none_or(|d| d < today))
}
fn source_host(source: &str, h: &str) -> bool {
    match source {
        "greenhouse" => matches!(h, "boards.greenhouse.io" | "job-boards.greenhouse.io"),
        "remotive" => h == "remotive.com",
        "arbeitnow" => matches!(h, "www.arbeitnow.com" | "arbeitnow.com"),
        "hacker_news" => h == "news.ycombinator.com",
        "lever" => matches!(h, "jobs.lever.co" | "jobs.eu.lever.co"),
        "ashby" => h == "jobs.ashbyhq.com",
        "smartrecruiters" => h == "jobs.smartrecruiters.com",
        _ => false,
    }
}
fn hosted(url: &str, board: &str, source: &str, expected_host: &str, application: bool) -> bool {
    let Ok(u) = reqwest::Url::parse(url) else {
        return false;
    };
    if u.scheme() != "https"
        || u.host_str() != Some(expected_host)
        || u.query().is_some_and(|q| !q.is_empty())
        || u.fragment().is_some_and(|s| !s.is_empty())
    {
        return false;
    }
    let path = u.path().strip_suffix('/').unwrap_or(u.path());
    let parts: Vec<_> = path.split('/').collect();
    let suffix = if source == "lever" {
        "apply"
    } else {
        "application"
    };
    (parts.len() == 3 || application && parts.len() == 4 && parts[3] == suffix)
        && parts[0].is_empty()
        && parts[1].eq_ignore_ascii_case(board)
        && !parts[2].is_empty()
        && parts[2].len() <= 100
        && parts[2]
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-')
}
#[derive(PartialEq, Eq)]
struct SmartIdentity {
    board: String,
    job: String,
    query: Vec<(String, String)>,
}
fn smart_identity(url: &str) -> Option<SmartIdentity> {
    let u = reqwest::Url::parse(url).ok()?;
    if u.host_str() != Some("jobs.smartrecruiters.com") {
        return None;
    }
    static PATH: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^/([A-Za-z0-9_-]+)/([0-9]{5,})(?:-[A-Za-z0-9_%~-]+)?$").unwrap()
    });
    let parts = PATH.captures(u.path().trim_end_matches('/'))?;
    let mut query = u
        .query_pairs()
        .filter(|(key, value)| {
            !value.is_empty()
                && key != "oga"
                && !lowered(key).starts_with("utm_")
                && ![
                    "fbclid",
                    "gclid",
                    "ref",
                    "referrer",
                    "source",
                    "trk",
                    "trackingid",
                    "gh_src",
                ]
                .contains(&lowered(key).as_str())
        })
        .map(|(a, b)| (a.into_owned(), b.into_owned()))
        .collect::<Vec<_>>();
    query.sort();
    Some(SmartIdentity {
        board: parts[1].into(),
        job: parts[2].into(),
        query,
    })
}
fn application_page(url: &str, policy: &Policy) -> Option<String> {
    let u = reqwest::Url::parse(url).ok()?;
    let h = u.host_str()?;
    if u.query()
        .is_some_and(|q| !q.is_empty() && !(h == "jobs.smartrecruiters.com" && q == "oga=true"))
        || u.fragment().is_some_and(|s| !s.is_empty())
        || [
            "linkedin.com",
            "naukri.com",
            "wellfound.com",
            "instahyre.com",
            "internshala.com",
            "accounts.google.com",
            "simplify.jobs",
            "mail.google.com",
        ]
        .iter()
        .any(|restricted| h == *restricted || h.ends_with(&format!(".{restricted}")))
    {
        return None;
    }
    static GH: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^/[A-Za-z0-9_-]+/jobs/[A-Za-z0-9_-]+/?$").unwrap());
    static LA: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^/[A-Za-z0-9_-]+/[A-Za-z0-9-]+(?:/(?:apply|application))?/?$").unwrap()
    });
    static SR: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^/[A-Za-z0-9_-]+/[0-9]+(?:-[A-Za-z0-9_%~-]+)?/?$").unwrap());
    static WD: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com$").unwrap());
    let known = matches!(h, "boards.greenhouse.io" | "job-boards.greenhouse.io")
        && GH.is_match(u.path())
        || matches!(h, "jobs.lever.co" | "jobs.eu.lever.co" | "jobs.ashbyhq.com")
            && LA.is_match(u.path())
        || h == "jobs.smartrecruiters.com" && SR.is_match(u.path())
        || WD.is_match(h)
            && u.path().contains("/job/")
            && u.path().trim_matches('/').split('/').count() >= 4
        || h == "docs.google.com" && u.path().starts_with("/forms/");
    (known
        || policy
            .origins
            .iter()
            .any(|o| o == &format!("https://{h}:443")))
    .then(|| url.into())
}
pub fn manual_page(value: &str, policy: &Policy) -> Option<String> {
    let url = public_https(value)?;
    let u = reqwest::Url::parse(&url).ok()?;
    let h = u.host_str()?;
    if u.fragment().is_some_and(|s| !s.is_empty()) {
        return None;
    }
    if matches!(h, "naukri.com" | "www.naukri.com") {
        static PATH: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"^/job-listings-[a-zA-Z0-9%_-]+-[0-9]{10,20}/?$").unwrap()
        });
        return (PATH.is_match(u.path()) && u.query().is_none_or(str::is_empty)).then_some(url);
    }
    static ZOHO: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^[a-z0-9][a-z0-9-]*\.zohorecruit\.(?:in|com)$").unwrap());
    if ZOHO.is_match(h) {
        static PATH: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"^/jobs/Careers/[0-9]+/[A-Za-z0-9_-]+/?$").unwrap());
        if !PATH.is_match(u.path()) {
            return None;
        }
        let query = u.query_pairs().collect::<Vec<_>>();
        let mut seen = std::collections::HashSet::new();
        if query.len() > 2
            || query.iter().any(|(k, v)| {
                !seen.insert(k.to_string())
                    || !matches!(k.as_ref(), "source" | "ref")
                    || v.is_empty()
                    || v.len() > 100
                    || !v
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
            })
        {
            return None;
        }
        return Some(url);
    }
    application_page(&url, policy)
}
pub fn select(
    job: &Value,
    observations: &[(String, String)],
    policy: &Policy,
    today: NaiveDate,
) -> Result<Selection> {
    let source = text(job, "source_platform")?;
    let original = job["job_url"].as_str().and_then(public_https);
    let application = job["application_url"].as_str().and_then(public_https);
    let observed = observations
        .iter()
        .filter(|(s, _)| s == "naukri")
        .filter_map(|(_, url)| public_https(url))
        .find(|url| naukri(url));
    let platform = if source == "manual_browser" {
        Some("manual_browser")
    } else if folded(source) == "naukri"
        || original.as_deref().is_some_and(naukri)
        || observed.is_some()
    {
        Some("naukri")
    } else {
        SOURCES.iter().copied().find(|s| *s == source)
    };
    let empty = || Destination {
        application_url: None,
        kind: "unknown",
        valid: false,
        source_confidence: "unverified",
        warnings: vec![],
    };
    let Some(platform) = platform else {
        return Ok(Selection {
            platform: None,
            preparation_supported: false,
            destination: empty(),
        });
    };
    let destination = match platform {
        "naukri" => {
            let source_valid = original.as_deref().is_some_and(naukri);
            let consistent = source_valid && folded(source) == "naukri" || observed.is_some();
            let mut warnings=vec!["URL syntax was checked locally; availability and destination ownership have not been live verified".into()];
            if !consistent {
                warnings.push("Saved platform label and posting host disagree; confirm or correct the saved source".into());
            }
            let raw = job["application_url"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(String::from)
                .or_else(|| {
                    if source_valid {
                        job["job_url"].as_str().map(String::from)
                    } else {
                        observed
                    }
                });
            let url = raw.as_deref().and_then(public_https);
            let unavailable = posting_unavailable(job, today)?;
            Destination {
                kind: if unavailable || url.is_none() && raw.is_some() {
                    "expired_or_invalid"
                } else if let Some(url) = url.as_deref() {
                    if naukri(url) {
                        "naukri_hosted"
                    } else {
                        "employer_external"
                    }
                } else {
                    "unknown"
                },
                valid: !unavailable && url.is_some(),
                application_url: url,
                source_confidence: if consistent {
                    "source_consistent"
                } else {
                    "source_conflict"
                },
                warnings,
            }
        }
        "manual_browser" => {
            let mut destination = application;
            if destination.is_none()
                && policy.testing
                && let Some(raw) = job["application_url"].as_str()
                && let Ok(u) = reqwest::Url::parse(raw)
                && u.scheme() == "http"
                && u.host_str() == Some("127.0.0.1")
                && u.username().is_empty()
                && u.password().is_none()
                && u.fragment().is_none_or(str::is_empty)
                && policy.origins.iter().any(|o| {
                    o == &format!(
                        "http://127.0.0.1:{}",
                        u.port_or_known_default().unwrap_or(80)
                    )
                })
            {
                destination = Some(raw.into());
            }
            Destination {kind:"employer_external",valid:destination.is_some()&&job["status"]!="archived",application_url:destination,source_confidence:"unverified",warnings:vec!["Owner-supplied destination; confirm employer identity and automation permission".into(),"Assisted filling only; owner submits manually".into()]}
        }
        "owner_extension" => {
            let url = job["application_url"]
                .as_str()
                .and_then(|s| manual_page(s, policy));
            Destination {
                kind: if url.is_some() {
                    "employer_external"
                } else {
                    "unknown"
                },
                valid: url
                    .as_ref()
                    .is_some_and(|s| job["job_url"].as_str() == Some(s))
                    && job["status"] != "archived",
                application_url: url,
                source_confidence: "unverified",
                warnings: vec![
                    "Owner-selected page; employer identity and vacancy are unverified".into(),
                    "Manual extension answers only; upload and submission remain owner-operated"
                        .into(),
                ],
            }
        }
        source => {
            let mut consistent = original
                .as_ref()
                .and_then(|s| host(s))
                .is_some_and(|h| source_host(source, &h));
            if matches!(source, "lever" | "ashby") {
                consistent &= original
                    .as_ref()
                    .zip(application.as_ref())
                    .is_some_and(|(a, b)| {
                        let u = reqwest::Url::parse(a).unwrap();
                        let v = reqwest::Url::parse(b).unwrap();
                        let board = u.path().trim_matches('/').split('/').next().unwrap_or("");
                        let suffix = if source == "lever" {
                            "/apply"
                        } else {
                            "/application"
                        };
                        hosted(a, board, source, u.host_str().unwrap_or(""), false)
                            && hosted(b, board, source, u.host_str().unwrap_or(""), true)
                            && v.path()
                                .trim_end_matches('/')
                                .strip_suffix(suffix)
                                .unwrap_or(v.path().trim_end_matches('/'))
                                == u.path().trim_end_matches('/')
                    });
            }
            if source == "smartrecruiters" {
                consistent &= original
                    .as_deref()
                    .and_then(smart_identity)
                    .zip(application.as_deref().and_then(smart_identity))
                    .is_some_and(|(a, b)| a == b);
            }
            Destination {
                kind: if application.is_some() {
                    "employer_external"
                } else {
                    "unknown"
                },
                valid: consistent
                    && application.is_some()
                    && job["source_verification_status"] == "source_reported"
                    && job["status"] != "archived",
                application_url: application,
                source_confidence: if consistent {
                    "source_consistent"
                } else {
                    "source_conflict"
                },
                warnings: vec![
                    "Verify employer ownership and vacancy on the official website before approval"
                        .into(),
                    "No form schema, upload, application receipt or submission is verified".into(),
                ],
            }
        }
    };
    Ok(Selection {
        platform: Some(platform),
        preparation_supported: true,
        destination,
    })
}
