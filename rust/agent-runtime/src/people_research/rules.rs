//! Pure existing search-index rules; no result URL fetch, credentials or provider grant.
use crate::{
    Failure, Result,
    research_contract::{self, Kind},
};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::LazyLock,
};
fn invalid() -> Failure {
    Failure("invalid_public_research_record")
}
pub fn query(input: &Value, now: DateTime<Utc>) -> Result<String> {
    let v = research_contract::normalize(Kind::PeopleQuery, input.clone(), now)?;
    let company = v["company_name"].as_str().ok_or_else(invalid)?;
    let roles = v["roles"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|r| r.as_str().ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?
        .join(" OR ");
    if v["research_mode"] == "official_company" {
        let domain = v["company_domain"]
            .as_str()
            .ok_or(Failure("public_research_official_domain_required"))?;
        return Ok(format!("site:{domain} \"{company}\" ({roles})"));
    }
    let mut text = format!("site:linkedin.com/in/ \"{company}\" ({roles})");
    for key in ["company_domain", "location"] {
        if let Some(s) = v[key].as_str() {
            text.push(' ');
            text.push_str(s)
        }
    }
    Ok(text)
}
fn aliases(role: &str) -> Result<&'static [&'static str]> {
    Ok(match role {
        "founder" => &["founder", "co-founder"],
        "co-founder" => &["co-founder", "cofounder"],
        "ceo" => &["ceo", "chief executive officer"],
        "cto" => &["cto", "chief technology officer"],
        "head of engineering" => &["head of engineering"],
        "vp engineering" => &["vp engineering", "vp of engineering"],
        "engineering manager" => &["engineering manager"],
        "technical recruiter" => &["technical recruiter"],
        "software engineer" => &["software engineer"],
        "software developer" => &["software developer"],
        "technical staff" => &[
            "software engineer",
            "software developer",
            "platform engineer",
        ],
        "talent acquisition" => &["talent acquisition"],
        "recruiter" => &["recruiter", "recruiting"],
        _ => return Err(invalid()),
    })
}
fn role(input: &Value, text: &str, official: bool) -> Result<Option<String>> {
    static PATTERNS: LazyLock<
        BTreeMap<&'static str, (crate::legacy_regex::Regex, crate::legacy_regex::Regex)>,
    > = LazyLock::new(|| {
        let roles = [
            "founder",
            "co-founder",
            "ceo",
            "cto",
            "head of engineering",
            "vp engineering",
            "engineering manager",
            "technical recruiter",
            "software engineer",
            "software developer",
            "technical staff",
            "talent acquisition",
            "recruiter",
        ];
        let mut all = BTreeSet::new();
        for role in roles {
            all.insert(role);
            all.extend(aliases(role).expect("fixed role aliases").iter().copied());
        }
        all.into_iter()
            .map(|word| {
                (
                    word,
                    (
                        crate::legacy_regex::Regex::literal_word(word, false),
                        crate::legacy_regex::Regex::literal_word(word, true),
                    ),
                )
            })
            .collect()
    });
    let text = if official {
        text.to_owned()
    } else {
        folded(text)
    };
    for r in input["roles"].as_array().ok_or_else(invalid)? {
        let r = r.as_str().ok_or_else(invalid)?;
        if official {
            if PATTERNS.get(r).ok_or_else(invalid)?.1.is_match(&text)? {
                return Ok(Some(r.into()));
            }
        } else {
            for word in aliases(r)? {
                if PATTERNS.get(word).ok_or_else(invalid)?.0.is_match(&text)? {
                    return Ok(Some(r.into()));
                }
            }
        }
    }
    Ok(None)
}
fn name(title: &str) -> Option<&str> {
    title.char_indices().find_map(|(at, c)| {
        if !matches!(c, '|' | '–' | '—' | '-') {
            return None;
        }
        let before = &title[..at];
        let after = &title[at + c.len_utf8()..];
        (before
            .chars()
            .next_back()
            .is_some_and(crate::context_contract::python_space)
            && after
                .chars()
                .next()
                .is_some_and(crate::context_contract::python_space))
        .then(|| before.trim_matches(crate::context_contract::python_space))
    })
}
fn evidence(record: &Value) -> Result<(&str, String)> {
    // False-like empty values match the original adapter; truthy nontext is invalid.
    let text = |key: &str| -> Result<&str> {
        match record.get(key) {
            None | Some(Value::Null) => Ok(""),
            Some(v) if !crate::contacts::rules::truthy(v) => Ok(""),
            Some(Value::String(s)) => Ok(s),
            _ => Err(invalid()),
        }
    };
    if !record.is_object() {
        return Err(invalid());
    }
    let title = text("title")?;
    let snippet = text("snippet")?;
    if title.chars().count() > 10000 || snippet.chars().count() > 16000 {
        return Err(invalid());
    }
    Ok((title, format!("{title} {snippet}")))
}
pub fn public_profiles(records: &Value, input: &Value, now: DateTime<Utc>) -> Result<Value> {
    let input = research_contract::normalize(Kind::PeopleQuery, input.clone(), now)?;
    if input["research_mode"] != "public_profiles" {
        return Err(invalid());
    }
    let rows = records.as_array().ok_or_else(invalid)?;
    if records.to_string().len() > 1048576 {
        return Err(Failure("public_research_response_limit"));
    }
    let limit = input["limit"].as_u64().ok_or_else(invalid)? as usize;
    let company = input["company_name"].as_str().ok_or_else(invalid)?;
    let mut people = Vec::new();
    let mut errors = Vec::new();
    for row in rows.iter().take(limit) {
        let parsed = (|| -> Result<Value> {
            let (title, text) = evidence(row)?;
            let role = role(&input, &text, false)?;
            let name = name(title).filter(|s| !s.is_empty() && s.chars().count() <= 100);
            let matched = folded(&text).contains(&folded(company));
            research_contract::normalize(
                Kind::PublicPerson,
                json!({"name":name,"role":role,"linkedin_url":row["link"],"evidence_url":row["link"],"source":"public_search","evidence_text":format!("Search-index candidate for {company}; reported role: {}; independent identity review required",role.as_deref().unwrap_or("unknown")),"verification_status":if matched && role.is_some(){"source_reported"}else{"requires_review"}}),
                now,
            )
        })();
        match parsed {
            Ok(v) => people.push(v),
            Err(_) => errors.push("public_search_record_invalid"),
        }
    }
    Ok(json!({"people":people,"errors":errors}))
}
pub fn official_people(
    records: &Value,
    input: &Value,
    now: DateTime<Utc>,
    permission: &str,
) -> Result<Value> {
    let input = research_contract::normalize(Kind::PeopleQuery, input.clone(), now)?;
    if input["research_mode"] != "official_company" {
        return Err(invalid());
    }
    let rows = records.as_array().ok_or_else(invalid)?;
    if records.to_string().len() > 1048576 {
        return Err(Failure("public_research_response_limit"));
    }
    let limit = input["limit"].as_u64().ok_or_else(invalid)? as usize;
    let company = input["company_name"].as_str().ok_or_else(invalid)?;
    let domain = input["company_domain"]
        .as_str()
        .ok_or(Failure("public_research_official_domain_required"))?;
    let permission = crate::resources::public_https(permission)
        .ok_or(Failure("public_research_permission_required"))?;
    let mut people = Vec::new();
    for row in rows.iter().take(limit) {
        let parsed = (|| -> Result<Option<Value>> {
            if !official_url(&row["link"], domain) {
                return Ok(None);
            }
            let (title, text) = evidence(row)?;
            let Some(role) = role(&input, &text, true)? else {
                return Ok(None);
            };
            let Some(name) = name(title) else {
                return Ok(None);
            };
            if !(2..=5).contains(
                &name
                    .split(crate::context_contract::python_space)
                    .filter(|s| !s.is_empty())
                    .count(),
            ) || !folded(&text).contains(&folded(company))
            {
                return Ok(None);
            }
            research_contract::normalize(Kind::OfficialPerson,json!({"full_name":name,"role_title":role,"evidence_url":row["link"],"permission_evidence_url":permission,"observed_at":now.to_rfc3339(),"human_confirmed":false}),now).map(Some)
        })();
        if let Ok(Some(v)) = parsed {
            people.push(v)
        }
    }
    Ok(json!({"people":people,"errors":[]}))
}
pub fn official_url(value: &Value, domain: &str) -> bool {
    value
        .as_str()
        .and_then(crate::resources::public_https)
        .and_then(|s| reqwest::Url::parse(&s).ok())
        .and_then(|u| u.host_str().map(String::from))
        .is_some_and(|h| h == domain || h == format!("www.{domain}"))
}
pub fn unique_people(people: Vec<Value>, now: DateTime<Utc>) -> Result<Vec<Value>> {
    if people.len() > 20 {
        return Err(invalid());
    }
    let mut unique = Vec::new();
    let mut urls = BTreeSet::new();
    let mut names: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for person in people {
        let person = research_contract::normalize(Kind::PublicPerson, person, now)?;
        let url = person["linkedin_url"]
            .as_str()
            .ok_or_else(invalid)?
            .to_owned();
        if !urls.insert(url.clone()) {
            continue;
        }
        if let Some(name) = person["name"].as_str().filter(|s| !s.is_empty()) {
            names.entry(folded(name)).or_default().insert(url);
        }
        unique.push(person);
    }
    for person in &mut unique {
        if person["name"]
            .as_str()
            .is_some_and(|name| names.get(&folded(name)).is_some_and(|urls| urls.len() > 1))
        {
            person["verification_status"] = json!("requires_review");
        }
    }
    Ok(unique)
}
