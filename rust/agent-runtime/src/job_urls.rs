//! Deterministic legacy job URL identity; syntax normalization performs no network IO.
use crate::{Failure, Result};
fn invalid() -> Failure {
    Failure("invalid_naukri_import")
}
fn query(pairs: Vec<(String, String)>) -> String {
    let mut encode = reqwest::Url::parse("https://example.org/").expect("fixed URL");
    encode.query_pairs_mut().clear().extend_pairs(pairs);
    encode
        .query()
        .unwrap_or("")
        .replace("%7E", "~")
        .replace('*', "%2A")
}
pub fn canonical(raw: &str) -> Result<String> {
    let safe = crate::resources::public_https(raw).ok_or_else(invalid)?;
    let mut url = reqwest::Url::parse(&safe).map_err(|_| invalid())?;
    if matches!(
        url.host_str(),
        Some("boards.greenhouse.io" | "job-boards.greenhouse.io")
    ) {
        url.set_host(Some("job-boards.greenhouse.io"))
            .map_err(|_| invalid())?;
    }
    let path = url.path().trim_end_matches('/').to_owned();
    url.set_path(if path.is_empty() { "/" } else { &path });
    let mut pairs = url
        .query_pairs()
        .filter(|(key, _)| {
            let key = key.to_lowercase();
            !key.starts_with("utm_")
                && !matches!(
                    key.as_str(),
                    "fbclid"
                        | "gclid"
                        | "ref"
                        | "referrer"
                        | "source"
                        | "trk"
                        | "trackingid"
                        | "gh_src"
                )
        })
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect::<Vec<_>>();
    pairs.sort();
    let encoded = query(pairs);
    url.set_query(if encoded.is_empty() {
        None
    } else {
        Some(&encoded)
    });
    url.set_fragment(None);
    Ok(url.into())
}
pub fn ats(raw: Option<&str>) -> Result<Option<String>> {
    let Some(raw) = raw else {
        return Ok(None);
    };
    let normalized = canonical(raw)?;
    let mut url = reqwest::Url::parse(&normalized).map_err(|_| invalid())?;
    let pattern = match url.host_str() {
        Some("job-boards.greenhouse.io") => r"^/[^/]+/jobs/[0-9]+$",
        Some("jobs.lever.co" | "jobs.eu.lever.co") => r"^/[^/]+/[A-Za-z0-9-]{10,}(?:/apply)?$",
        Some("jobs.ashbyhq.com") => r"^/[^/]+/[A-Za-z0-9-]{10,}(?:/application)?$",
        Some("jobs.smartrecruiters.com") => r"^/[A-Za-z0-9_-]+/[0-9]{5,}(?:-[A-Za-z0-9_%~-]+)?$",
        _ => return Ok(None),
    };
    if !regex::Regex::new(pattern)
        .expect("fixed ATS syntax")
        .is_match(url.path())
    {
        return Ok(None);
    }
    let path = url
        .path()
        .strip_suffix("/apply")
        .or_else(|| url.path().strip_suffix("/application"))
        .unwrap_or(url.path())
        .to_owned();
    url.set_path(&path);
    if url.host_str() == Some("jobs.smartrecruiters.com") {
        let regex = regex::Regex::new(r"(/[0-9]{5,})(?:-.*)?$").expect("fixed ATS suffix");
        let path = regex.replace(url.path(), "$1").into_owned();
        url.set_path(&path);
        let pairs = url
            .query_pairs()
            .filter(|(k, _)| k != "oga")
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect::<Vec<_>>();
        let encoded = query(pairs);
        url.set_query(if encoded.is_empty() {
            None
        } else {
            Some(&encoded)
        });
    }
    Ok(Some(url.into()))
}
