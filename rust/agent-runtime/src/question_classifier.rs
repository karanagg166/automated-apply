//! Conservative routing from the saved question; categories never establish personal facts.
use crate::link_resolver::{file_upload, normalize, resource_types};
use regex::Regex;
use serde::Serialize;
use std::{
    collections::HashMap,
    sync::{LazyLock, Mutex},
};

#[derive(Serialize, Debug, PartialEq, Eq)]
pub struct Classification {
    pub question_type: &'static str,
    pub field: Option<&'static str>,
}
fn result(question_type: &'static str, field: Option<&'static str>) -> Classification {
    Classification {
        question_type,
        field,
    }
}
/// The input has only frozen Python-word characters and spaces. This avoids Rust's
/// broader/newer Unicode word boundaries changing a classification (e.g. superscripts).
fn word(pattern: &'static str, text: &str) -> bool {
    static CACHE: LazyLock<Mutex<HashMap<&'static str, Regex>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    // This cache contains only immutable compiled local patterns, no authorization state.
    // Rebuild after poisoning instead of cascading a prior caller's panic.
    let mut cache = CACHE.lock().unwrap_or_else(|poisoned| {
        let mut cache = poisoned.into_inner();
        cache.clear();
        CACHE.clear_poison();
        cache
    });
    let regex = cache.entry(pattern).or_insert_with(|| {
        let body = pattern
            .strip_prefix(r"\b")
            .unwrap()
            .strip_suffix(r"\b")
            .unwrap()
            .replace(r"\w*", r"[^ ]*");
        Regex::new(&format!("(?:^| )({body})(?: |$)")).expect("public bounded classifier pattern")
    });
    regex.is_match(text)
}
pub fn canonical(question: &str) -> Option<&'static str> {
    static PHRASES: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
        [
        (r"(?:walk (?:me|us) through|share an example of) (?:a|your) project(?: (?:that )?you (?:built|developed|implemented))?","Describe a project you built"),
        (r"walk (?:me|us) through (?:a|your) (?:technically )?challenging project(?: (?:that )?you (?:built|developed|implemented))?","Describe a challenging project you built"),
        (r"(?:give (?:me|us) (?:a|your) (?:brief )?professional introduction|share (?:a|your) (?:short )?professional bio|tell (?:me|us) a little about yourself|briefly introduce yourself)","Introduce yourself"),
        (r"(?:what (?:attracts|drew|draws) you to (?:this|our) (?:company|role|position|opportunity)|what (?:excites|interests) you about (?:this|our) (?:company|role|position|opportunity)|what is your motivation for (?:applying|joining)(?: here)?)","Why do you want to join this company"),
        (r"what (?:attracts|drew|draws) you to (?:this|our) startup","Why do you want to join this startup"),
    ].into_iter().map(|(pattern,text)|(Regex::new(&format!("^(?:{pattern})$")).unwrap(),text)).collect()
    });
    if question.chars().count() > 2000 {
        return None;
    }
    let text = normalize(question);
    PHRASES
        .iter()
        .find(|(pattern, _)| pattern.is_match(&text))
        .map(|(_, canonical)| *canonical)
}
pub fn classify(question: &str) -> Classification {
    let q = normalize(canonical(question).unwrap_or(question));
    if file_upload(&q) {
        return result("file_upload", None);
    }
    if !resource_types(&q).is_empty()
        && !word(
            r"\b(explain|describe|experience|built|challeng\w*|tell us|why|how did)\b",
            &q,
        )
    {
        return result("profile_link", None);
    }
    const FIELDS: &[(&str, &str)] = &[
        (r"\b(e mail|email)\b", "email"),
        (r"\b(phone|mobile|telephone)\b", "phone"),
        (r"\b(full name|your name)\b", "full_name"),
        (
            r"\b(years of (?:professional |work |total )?experience|experience (?:in )?years|total experience)\b",
            "verified_experience_years",
        ),
        (r"\bnotice period\b", "notice_period_days"),
        (r"\b(?:verified |technical )?skills\b", "verified_skills"),
        (
            r"\btechnologies (?:have you |you have )?used\b",
            "verified_skills",
        ),
        (r"\beducation(?:al background)?\b", "education"),
        (r"\bcertifications?\b", "certifications"),
        (r"\bremote (?:work )?preference\b", "remote_preference"),
    ];
    let fields: Vec<_> = FIELDS
        .iter()
        .filter(|(pattern, _)| word(pattern, &q))
        .map(|(_, field)| *field)
        .collect();
    if !fields.is_empty() {
        if word(
            r"\b(salary|compensation|ctc|sponsorship|visa|authorization|authorisation|relocation|availability)\b",
            &q,
        ) || fields.len() != 1
            || word(
                r"\b(explain|describe|tell|why|project|using|with|in python|in java)\b",
                &q,
            )
        {
            return result("unknown", None);
        }
        return result("personal_details", Some(fields[0]));
    }
    if word(
        r"\b(authorization|authorisation|visa|sponsorship|authorized to work|authorised to work|legally authorized|legally authorised|right to work)\b",
        &q,
    ) {
        return result("work_authorization", Some("work_authorization"));
    }
    if word(r"\b(salary|compensation|ctc|pay expectation)\b", &q) {
        return result(
            "compensation",
            q.contains("minimum").then_some("minimum_salary"),
        );
    }
    if word(
        r"\b(project|built|build|best work|impressive thing|proudest|accomplishment)\b",
        &q,
    ) {
        return result("project_explanation", None);
    }
    if word(r"\b(startup|founder|founding)\b", &q)
        && word(r"\b(why|interest|join|motivat)\w*\b", &q)
    {
        return result("startup_interest", None);
    }
    if word(r"\b(why|motivat\w*)\b", &q) {
        return result("motivation", None);
    }
    if word(
        r"\b(technical|implemented|engineering|apis?|integrated|bug|experience (?:with|using|in)|worked with|production issue)\b",
        &q,
    ) {
        return result("technical_experience", None);
    }
    if word(
        r"\b(about yourself|introduce yourself|professional summary|short bio)\b",
        &q,
    ) {
        return result("short_text", None);
    }
    result("unknown", None)
}
