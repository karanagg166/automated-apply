//! Bounded selection of already verified professional facts; skills alone prove no work.
use crate::{Failure, Result, profile_contract::legacy_word, resources::ascii_string};
use automated_apply_domain::text::folded;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::{
    collections::{BTreeSet, HashSet},
    sync::LazyLock,
};
use uuid::Uuid;

#[derive(Deserialize)]
pub struct Evidence {
    pub id: Uuid,
    pub title: String,
    pub content: String,
    pub user_confirmed: bool,
    pub project: Option<Value>,
}
#[derive(Serialize)]
pub struct Fact {
    pub reference: Reference,
    pub facts: Value,
    pub score: usize,
}
#[derive(Serialize)]
pub struct Reference {
    pub source_type: &'static str,
    pub source_id: String,
}
pub fn tokens(value: &str) -> BTreeSet<String> {
    static TOKEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[a-z0-9+#.]+").unwrap());
    const STOP: &str = "tell us about your a an the my i and or what most how have with you to of it in is thing describe built project work experience technical";
    TOKEN
        .find_iter(&folded(value))
        .map(|m| m.as_str().to_owned())
        .filter(|s| !STOP.split(' ').any(|word| word == s))
        .collect()
}
fn named(value: &str) -> String {
    folded(value)
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        .collect()
}
fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => v.as_f64() != Some(0.0),
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
/// ASCII serialization is needed for legacy skill gates, not for prompts or output.
fn ascii_json(value: &Value) -> String {
    match value {
        Value::String(s) => ascii_string(s),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(ascii_json).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(key, value)| format!("{}: {}", ascii_string(key), ascii_json(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => value.to_string(),
    }
}
fn insensitive(text: &str) -> (String, Vec<usize>) {
    let mut out = String::new();
    let mut offsets = Vec::new();
    for (index, c) in text.char_indices() {
        let c = match c {
            'İ' | 'ı' => 'i',
            'ſ' => 's',
            'K' => 'k',
            c => c.to_ascii_lowercase(),
        };
        offsets.extend(std::iter::repeat_n(index, c.len_utf8()));
        out.push(c);
    }
    offsets.push(text.len());
    (out, offsets)
}
fn bounded(text: &str, start: usize, end: usize) -> bool {
    !text[..start].chars().next_back().is_some_and(legacy_word)
        && !text[end..].chars().next().is_some_and(legacy_word)
}
fn challenge(question: &str) -> bool {
    let (text, _) = insensitive(question);
    if ["challeng", "problem", "solv"]
        .iter()
        .any(|s| text.contains(s))
    {
        return true;
    }
    static EXACT: LazyLock<Regex> = LazyLock::new(|| Regex::new("bugs?|failure").unwrap());
    if EXACT
        .find_iter(&text)
        .any(|m| bounded(&text, m.start(), m.end()))
    {
        return true;
    }
    text.match_indices("debug")
        .any(|(start, _)| !text[..start].chars().next_back().is_some_and(legacy_word))
}
fn personally_attributable(content: &str) -> bool {
    static WORK: LazyLock<Regex> =
        LazyLock::new(|| Regex::new("i (?:built|implemented|worked|developed|designed)").unwrap());
    let (text, _) = insensitive(content);
    WORK.find_iter(&text)
        .any(|m| bounded(&text, m.start(), m.end()))
}
fn requested(question: &str) -> Option<BTreeSet<String>> {
    static REQUEST: LazyLock<Regex> =
        LazyLock::new(|| Regex::new("(?:experience (?:with|using|in)|worked with)").unwrap());
    let (text, offsets) = insensitive(question);
    for found in REQUEST.find_iter(&text) {
        let tail = &question[offsets[found.end()]..];
        let whitespace = |c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c);
        if !tail.chars().next().is_some_and(whitespace) {
            continue;
        }
        let tail = tail
            .trim_start_matches(whitespace)
            .split('\n')
            .next()
            .unwrap_or("");
        if !tail.is_empty() {
            return Some(tokens(tail));
        }
    }
    None
}
pub fn retrieve(
    profile: &Value,
    evidence: &[Evidence],
    question: &str,
    category: &str,
) -> Result<Vec<Fact>> {
    let id = profile["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_verified_context"))?;
    let projects = profile["projects"]
        .as_array()
        .ok_or(Failure("invalid_verified_context"))?;
    let roles = profile["verified_roles"]
        .as_array()
        .ok_or(Failure("invalid_verified_context"))?;
    let skills = profile["verified_skills"]
        .as_array()
        .ok_or(Failure("invalid_verified_context"))?;
    if evidence.len() > 100
        || projects.len() > 100
        || roles.len() > 100
        || question.chars().count() > 2000
    {
        return Err(Failure("verified_evidence_limit"));
    }
    let names: HashSet<_> = projects
        .iter()
        .filter_map(|p| p["name"].as_str())
        .filter(|s| !s.is_empty())
        .map(named)
        .filter(|name| named(question).contains(name))
        .collect();
    let query = tokens(question);
    let challenging = challenge(question);
    let mut facts = Vec::new();
    let mut add = |source_type, source_id: String, data: Value, rank: usize| {
        let words = tokens(&serde_json::to_string(&data).unwrap());
        facts.push(Fact {
            reference: Reference {
                source_type,
                source_id,
            },
            facts: data,
            score: query.intersection(&words).count() + rank,
        });
    };
    let eligible = |project: &Value| -> bool {
        (names.is_empty() || names.contains(&named(project["name"].as_str().unwrap_or(""))))
            && truth(&project["contribution"])
            && (truth(&project["purpose"]) || truth(&project["description"]))
            && (!challenging
                || truth(&project["engineering_challenges"]) && truth(&project["solutions"]))
    };
    if matches!(category, "project_explanation" | "technical_experience") {
        for (i, project) in projects.iter().enumerate() {
            if eligible(project) {
                add(
                    "verified_project",
                    format!("{id}:project:{i}"),
                    project.clone(),
                    2,
                );
            }
        }
        for item in evidence.iter().filter(|item| item.user_confirmed) {
            if let Some(project) = item.project.as_ref().filter(|p| truth(p)) {
                if eligible(project) {
                    add(
                        "candidate_evidence",
                        item.id.to_string(),
                        json!({"project":project}),
                        2,
                    );
                }
            } else if names.is_empty()
                && category == "technical_experience"
                && personally_attributable(&item.content)
            {
                add(
                    "candidate_evidence",
                    item.id.to_string(),
                    json!({"title":item.title,"content":item.content}),
                    0,
                );
            }
        }
        if names.is_empty() && category == "technical_experience" {
            for (i, role) in roles.iter().enumerate() {
                if truth(&role["highlight"]) {
                    add("verified_role", format!("{id}:role:{i}"), role.clone(), 0);
                }
            }
        }
        if let Some(requested) = requested(question).filter(|s| !s.is_empty()) {
            facts.retain(|fact| !requested.is_disjoint(&tokens(&ascii_json(&fact.facts))));
        }
        let mentioned: Vec<_> = skills
            .iter()
            .filter_map(Value::as_str)
            .map(folded)
            .filter(|s| folded(question).contains(s))
            .collect();
        if !mentioned.is_empty() {
            facts.retain(|fact| {
                let text = folded(&ascii_json(&fact.facts));
                mentioned.iter().all(|skill| text.contains(skill))
            });
        }
    } else if matches!(category, "motivation" | "startup_interest") {
        let mut preferences = Map::new();
        let values = profile["preferences"]
            .as_object()
            .ok_or(Failure("invalid_verified_context"))?;
        for key in [
            "target_titles",
            "technology_stacks",
            "target_industries",
            "company_stages",
            "prioritize_startups",
        ] {
            if let Some(value) = values.get(key)
                && !value.is_null()
                && value != &json!([])
                && value != &json!(false)
                && value.as_f64() != Some(0.0)
            {
                preferences.insert(key.into(), value.clone());
            }
        }
        if !preferences.is_empty() {
            add(
                "candidate_preferences",
                id.to_string(),
                Value::Object(preferences),
                0,
            );
        }
    } else if category == "short_text" {
        let mut data = Map::new();
        for key in ["summary", "verified_roles", "education", "certifications"] {
            if truth(&profile[key]) {
                data.insert(key.into(), profile[key].clone());
            }
        }
        if !data.is_empty() {
            add("candidate_profile", id.to_string(), Value::Object(data), 0);
        }
    }
    facts.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| a.reference.source_id.cmp(&b.reference.source_id))
    });
    facts.truncate(6);
    Ok(facts)
}
