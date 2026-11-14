//! Deterministic links only. Free-text questions cannot grant tool or upload authority.
use crate::{
    Failure, Result, profile_contract,
    resources::{self, Resource},
};
use automated_apply_domain::text::folded;
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};
const ALIASES: &[(&str, &[&str])] = &[
    ("github", &["github", "git hub"]),
    ("linkedin", &["linkedin", "linked in"]),
    ("portfolio", &["portfolio", "personal website"]),
    ("resume", &["resume", "résumé", "cv", "curriculum vitae"]),
    ("leetcode", &["leetcode", "leet code"]),
    ("codeforces", &["codeforces", "code forces"]),
    (
        "geeksforgeeks",
        &["geeksforgeeks", "geeks for geeks", "gfg"],
    ),
    ("hackerrank", &["hackerrank", "hacker rank"]),
    ("kaggle", &["kaggle"]),
];
pub(crate) fn normalize(text: &str) -> String {
    folded(text)
        .chars()
        .map(|c| {
            if profile_contract::legacy_word(c) {
                c
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
fn phrase_in(phrase: &str, text: &str) -> bool {
    format!(" {} ", normalize(text)).contains(&format!(" {} ", normalize(phrase)))
}
pub(crate) fn resource_types(question: &str) -> HashSet<&'static str> {
    ALIASES
        .iter()
        .filter(|(_, aliases)| aliases.iter().any(|alias| phrase_in(alias, question)))
        .map(|(kind, _)| *kind)
        .collect()
}
pub(crate) fn file_upload(question: &str) -> bool {
    [
        "upload",
        "attach",
        "attachment",
        "browse file",
        "choose file",
        "select file",
    ]
    .iter()
    .any(|word| phrase_in(word, question))
}
pub fn question(input: Value) -> Result<String> {
    let body = input.as_object().ok_or(Failure("invalid_resource_input"))?;
    if body.len() != 1 {
        return Err(Failure("invalid_resource_input"));
    }
    let question = body
        .get("question")
        .and_then(Value::as_str)
        .ok_or(Failure("invalid_resource_input"))?
        .trim();
    if question.is_empty() || question.chars().count() > 2000 {
        return Err(Failure("invalid_resource_input"));
    }
    Ok(question.into())
}
fn missing(mut result: Value, text: &str) -> Value {
    result["missing_information"] = json!([text]);
    result
}
fn answer(mut result: Value, url: Value, source: Value, confirmed: bool) -> Value {
    result["answer"] = url;
    result["source"] = source;
    result["confidence"] = json!(if confirmed { 1.0 } else { 0.75 });
    result["status"] = json!("draft_ready");
    result["requires_review"] = json!(!confirmed);
    result
}
pub fn resolve(
    profile: &Value,
    resources: &[Resource],
    defaults: &BTreeMap<String, String>,
    question: &str,
) -> Value {
    let kinds = resource_types(question);
    let mut result = crate::answer_contract::result("profile_link", "professional");
    if file_upload(question) {
        result["question_type"] = json!("file_upload");
        result["status"] = json!("file_upload_required");
        let mut items:Vec<_>=resources.iter().filter(|r|r.resource_type=="resume").take(100).map(|r|json!({"id":r.id,"label":r.label,"url":r.url,"user_confirmed":r.user_confirmed,"accessibility":"not_checked"})).collect();
        let link = resources::resolved_link(profile, resources, defaults, "resume");
        if items.is_empty() && !link["url"].is_null() {
            items.push(
                json!({"url":link["url"],"source":link["source"],"accessibility":"not_checked"}),
            );
        }
        result["resources"] = json!(items);
        return missing(
            result,
            "Select and upload an actual file in the application form; no file was uploaded",
        );
    }
    if [
        "explain",
        "describe",
        "experience",
        "built",
        "tell us",
        "why",
        "how did",
    ]
    .iter()
    .any(|word| phrase_in(word, question))
        || normalize(question)
            .split(' ')
            .any(|word| word.starts_with("challeng"))
    {
        return missing(
            result,
            "This question requires more than a saved profile link",
        );
    }
    let generic: HashSet<_> = ALIASES
        .iter()
        .flat_map(|(_, aliases)| aliases.iter().map(|alias| normalize(alias)))
        .collect();
    let labels: Vec<_> = resources
        .iter()
        .filter(|r| {
            r.user_confirmed
                && !generic.contains(&normalize(&r.label))
                && phrase_in(&r.label, question)
        })
        .collect();
    if kinds.len() > 1 {
        return missing(result, "Ask for one resource type at a time");
    }
    if !labels.is_empty() {
        let matches: Vec<_> = labels
            .into_iter()
            .filter(|r| kinds.is_empty() || kinds.contains(r.resource_type.as_str()))
            .collect();
        if matches.len() == 1
            && let Some(url) = resources::public_https(&matches[0].url)
        {
            return answer(result, json!(url), json!("candidate_resource"), true);
        }
        return missing(
            result,
            "Several resources match this label; specify a unique resource label",
        );
    }
    if [
        "project",
        "projects",
        "repo",
        "repositories",
        "repository",
        "username",
        "email",
        "phone",
        "notice",
        "salary",
    ]
    .iter()
    .any(|word| phrase_in(word, question))
    {
        return missing(
            result,
            "Specify one profile URL or an exact saved resource label; this question asks for additional facts",
        );
    }
    if kinds.len() != 1 {
        return missing(result, "Specify a saved resource type or its exact label");
    }
    let kind = kinds.into_iter().next().unwrap();
    let link = resources::resolved_link(profile, resources, defaults, kind);
    if !link["url"].is_null() {
        return answer(
            result,
            link["url"].clone(),
            link["source"].clone(),
            link["user_confirmed"] == true,
        );
    }
    let mut title = kind.to_owned();
    title.get_mut(..1).unwrap().make_ascii_uppercase();
    missing(
        result,
        &format!("{title} profile URL has not been configured, confirmed, or uniquely selected"),
    )
}
