//! Untrusted import suggestions only; never profile facts or automatic confirmation.
use crate::{Result, grounding, legacy_regex::Regex};
use serde_json::{Value, json};
use std::sync::LazyLock;
pub fn suggestions(text: &str) -> Result<Value> {
    static EMAIL: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", false));
    static NAME: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"^[A-Za-z][A-Za-z .'-]{2,100}$", false));
    const SKILLS: &[&str] = &[
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Redis",
        "Next.js",
        "React",
        "TypeScript",
        "Node.js",
        "RAG",
        "LangChain",
        "Docker",
        "Java",
        "C++",
        "JavaScript",
        "SQL",
        "Git",
    ];
    static PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
        SKILLS
            .iter()
            .map(|s| Regex::literal_word(s, true))
            .collect()
    });
    let mut name = "";
    for line in text
        .split([
            '\n', '\r', '\u{b}', '\u{c}', '\u{1c}', '\u{1d}', '\u{1e}', '\u{85}', '\u{2028}',
            '\u{2029}',
        ])
        .map(grounding::trim)
        .filter(|s| !s.is_empty())
        .take(3)
    {
        if NAME.is_match(line)? {
            name = line;
            break;
        }
    }
    let mut skills = vec![];
    for (skill, pattern) in SKILLS.iter().zip(PATTERNS.iter()) {
        if pattern.is_match(text)? {
            skills.push(*skill);
        }
    }
    let email = EMAIL
        .find(text)?
        .first()
        .map(|m| m.text.clone())
        .unwrap_or_default();
    Ok(json!({"full_name":name,"email":email,"verified_skills":skills}))
}
