//! Closed extractive answers: whole approved first-person sentences, never invented ownership.
use crate::{
    Failure, Result,
    evidence_retrieval::ascii_json,
    grounding::{self, Claim, Fact, ModelAnswer, Reference, trim, words},
    legacy_regex::Regex,
};
use automated_apply_domain::text::folded;
use serde::Serialize;
use serde_json::Value;
use std::{collections::BTreeSet, sync::LazyLock};

#[derive(Clone, Serialize)]
pub struct Clause {
    pub text: String,
    pub quote: String,
    pub source: Reference,
    pub topics: Vec<&'static str>,
}
#[derive(Default, Serialize)]
pub struct Prepared {
    pub clauses: Vec<Clause>,
    pub missing: Vec<String>,
    pub error: Option<&'static str>,
    pub sentence_count: Option<usize>,
}
#[derive(Clone, Copy)]
pub struct Instructions {
    pub max_characters: usize,
    pub max_words: Option<usize>,
}
fn error(code: &'static str) -> Prepared {
    Prepared {
        error: Some(code),
        ..Default::default()
    }
}
fn missing(messages: Vec<String>) -> Prepared {
    Prepared {
        missing: messages,
        ..Default::default()
    }
}
fn tokens(text: &str) -> BTreeSet<String> {
    static WORD: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new("[a-z0-9]+").unwrap());
    WORD.find_iter(&folded(text))
        .map(|m| m.as_str().into())
        .collect()
}
fn covers(topic: &str, clause: &Clause) -> Result<bool> {
    if clause.topics.contains(&topic) {
        return Ok(true);
    }
    static PATTERNS: LazyLock<Vec<(&str, Regex)>> = LazyLock::new(|| {
        [
            ("users", r"\busers\b"),
            ("revenue", r"\brevenue\b"),
            ("achievement", r"\bachievement\b"),
            ("salary", r"\bsalary\b"),
            ("team size", r"\bteam size\b"),
            ("latency", r"\blatency\b"),
            ("challenge", r"\b(?:challeng\w*|bugs?|failure)\b"),
            ("API", r"\bAPIs?\b"),
            (
                "solution",
                r"\b(?:fix(?:ed)?|solv(?:e|ed)|resolv(?:e|ed)|solution)\b",
            ),
            ("decision", r"\b(?:decision|tradeoff|trade-off)\b"),
        ]
        .into_iter()
        .map(|(topic, pattern)| (topic, Regex::new(pattern, true)))
        .collect()
    });
    PATTERNS
        .iter()
        .find(|(key, _)| *key == topic)
        .ok_or(Failure("invalid_evidence_topic"))?
        .1
        .is_match(&clause.text)
}
fn any_cover(topic: &str, clauses: &[Clause]) -> Result<bool> {
    for clause in clauses {
        if covers(topic, clause)? {
            return Ok(true);
        }
    }
    Ok(false)
}
pub fn prepare(question: &str, context: &Value, instructions: Instructions) -> Result<Prepared> {
    if question.chars().count() > 2000 || ascii_json(context).len() > 12000 {
        return Ok(error("input_size_exceeded"));
    }
    let empty = Value::Array(Vec::new());
    let raw = context.get("evidence").unwrap_or(&empty);
    let Some(evidence) = raw.as_array().filter(|rows| rows.len() <= 6) else {
        return Ok(error("invalid_evidence"));
    };
    static COUNT: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b(two|three|[1-8]) sentences?\b", true));
    let count =
        COUNT
            .first_group(question, 1)?
            .map(|token| match token.to_ascii_lowercase().as_str() {
                "two" => 2,
                "three" => 3,
                number => number.parse::<usize>().unwrap(),
            });
    static REQUIREMENTS: LazyLock<Vec<(&str, Regex)>> = LazyLock::new(|| {
        [
        ("users",r"\busers?\b"),("revenue",r"\brevenue\b"),("achievement",r"\b(?:awards?|achievements?)\b"),("salary",r"\b(?:salary|compensation)\b"),
        ("team size",r"\bteam\s+size\b"),("latency",r"\blatency\b"),("challenge",r"\b(?:challenge|challenges|bug|bugs|failure)\b|\bchallenging(?=\s+(?:technical\s+)?(?:bug|issue|problem)\b)"),
        ("API",r"\bAPIs?\b"),("decision",r"\b(?:why|decision|decisions)\b"),
    ].into_iter().map(|(topic,pattern)|(topic,Regex::new(pattern,true))).collect()
    });
    let mut requirements = Vec::new();
    for (topic, regex) in REQUIREMENTS.iter() {
        if regex.is_match(question)? {
            requirements.push(*topic);
        }
    }
    static SOLUTION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"\b(?:fix(?:ed)?|solv(?:e|ed)|resolv(?:e|ed)|solution)\b",
            true,
        )
    });
    if requirements.contains(&"challenge") && SOLUTION.is_match(question)? {
        requirements.push("solution");
    }
    static INJECTION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"ignore\s|instructions?|system\s|execute[_ ]|https?://|print\s|disclose\s|override\s|call\s.*tool|rules?|sentinel|INJECTION_",
            true,
        )
    });
    static PERSON: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(?:I|my)\b", true));
    const FIELDS: &[&str] = &[
        "summary",
        "description",
        "purpose",
        "contribution",
        "notes",
        "content",
        "highlight",
        "engineering_challenges",
        "solutions",
        "technologies",
        "stack",
    ];
    let query = tokens(question);
    let mut candidates: Vec<(usize, Vec<Clause>)> = Vec::new();
    for fact in evidence {
        let Some(source) = fact
            .get("reference")
            .cloned()
            .and_then(|raw| Reference::parse(raw).ok())
        else {
            return Ok(error("invalid_evidence_reference"));
        };
        let Some(data) = fact.get("facts") else {
            return Ok(error("invalid_evidence_reference"));
        };
        if !data.is_object() {
            continue;
        }
        let data = data.get("project").unwrap_or(data);
        if !data.is_object() {
            continue;
        }
        let mut clauses = Vec::new();
        let mut seen = BTreeSet::new();
        for field in FIELDS {
            let Some(value) = data[*field].as_str() else {
                continue;
            };
            if INJECTION.is_match(value)? {
                continue;
            }
            for part in grounding::sentences(value)? {
                let quote = trim(part);
                if quote.is_empty() || quote.chars().count() > 4000 || !PERSON.is_match(quote)? {
                    continue;
                }
                if seen.insert(quote.to_owned()) {
                    let topics = match *field {
                        "engineering_challenges" => vec!["challenge"],
                        "solutions" => vec!["solution"],
                        _ => Vec::new(),
                    };
                    clauses.push(Clause {
                        text: quote.into(),
                        quote: quote.into(),
                        source: source.clone(),
                        topics,
                    });
                }
            }
        }
        if !clauses.is_empty() {
            let combined = clauses
                .iter()
                .map(|c| c.text.as_str())
                .collect::<Vec<_>>()
                .join(" ");
            let mut score = query.intersection(&tokens(&combined)).count();
            if let Some(name) = data["name"].as_str().filter(|s| !s.is_empty())
                && folded(question).contains(&folded(name))
            {
                score += 100;
            }
            candidates.push((score, clauses));
        }
    }
    if candidates.is_empty() {
        return Ok(missing(vec![
            "Provide approved first-person facts for the requested answer.".into(),
        ]));
    }
    let mut supported = Vec::new();
    for (index, (_, clauses)) in candidates.iter().enumerate() {
        let mut all = true;
        for topic in &requirements {
            if !any_cover(topic, clauses)? {
                all = false;
                break;
            }
        }
        if all {
            supported.push(index);
        }
    }
    if supported.is_empty() {
        supported.extend(0..candidates.len());
    }
    let mut best = supported[0];
    for index in supported.into_iter().skip(1) {
        if candidates[index].0 > candidates[best].0 {
            best = index;
        }
    }
    let mut clauses = candidates.swap_remove(best).1;
    let mut unknown = Vec::new();
    for topic in &requirements {
        if !any_cover(topic, &clauses)? {
            unknown.push(format!("Provide approved {topic} information."));
        }
    }
    if !unknown.is_empty() {
        return Ok(missing(unknown));
    }
    static USERS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b\d+\b.*\busers\b", true));
    if requirements.contains(&"users") {
        let mut supported = false;
        for clause in &clauses {
            if USERS.is_match(&clause.text)? {
                supported = true;
                break;
            }
        }
        if !supported {
            return Ok(missing(vec![
                "Provide an approved numeric user count.".into(),
            ]));
        }
    }
    if !requirements.is_empty() {
        let mut filtered = Vec::new();
        for clause in clauses {
            let mut keep = false;
            for topic in &requirements {
                if covers(topic, &clause)? {
                    keep = true;
                    break;
                }
            }
            if keep {
                filtered.push(clause);
            }
        }
        clauses = filtered;
    }
    static STACK: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b(?:stack|technologies)\b", true));
    static GENERAL: LazyLock<Regex> =
        LazyLock::new(|| Regex::new("features|describe|summary", true));
    static USES: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b(?:uses?|using|stack|technologies)\b", true));
    if STACK.is_match(question)? && !GENERAL.is_match(question)? {
        let mut filtered = Vec::new();
        for clause in clauses {
            if USES.is_match(&clause.text)? {
                filtered.push(clause);
            }
        }
        clauses = filtered;
    }
    let mut selected: Vec<Clause> = Vec::new();
    for clause in clauses.into_iter().take(8) {
        let answer = selected
            .iter()
            .map(|c| c.text.as_str())
            .chain(std::iter::once(clause.text.as_str()))
            .collect::<Vec<_>>()
            .join(" ");
        if answer.chars().count() <= instructions.max_characters
            && instructions
                .max_words
                .is_none_or(|max| words(&answer) <= max)
        {
            selected.push(clause);
        }
        if count.is_some_and(|n| selected.len() == n) {
            break;
        }
    }
    let mut complete = !selected.is_empty() && count.is_none_or(|n| selected.len() == n);
    for topic in &requirements {
        if !any_cover(topic, &selected)? {
            complete = false;
        }
    }
    if !complete {
        return Ok(error("output_constraints_unsatisfied"));
    }
    Ok(Prepared {
        clauses: selected,
        sentence_count: count,
        ..Default::default()
    })
}
pub fn match_answer(
    answer: &str,
    prepared: &Prepared,
    facts: &[Fact],
    instructions: Instructions,
) -> Result<(Option<ModelAnswer>, Option<&'static str>)> {
    let parts: Vec<_> = grounding::sentences(answer)?
        .into_iter()
        .map(trim)
        .filter(|s| !s.is_empty())
        .collect();
    if prepared.error.is_some() || !prepared.missing.is_empty() || prepared.clauses.is_empty() {
        return Ok((None, Some("evidence_not_prepared")));
    }
    if parts.len() != prepared.clauses.len() {
        return Ok((
            None,
            Some(if prepared.sentence_count.is_some() {
                "sentence_count_mismatch"
            } else {
                "clause_coverage_mismatch"
            }),
        ));
    }
    let mut remaining = prepared.clauses.clone();
    let mut claims = Vec::new();
    for part in parts {
        let found = remaining.iter().position(|c| {
            part == c.text
                || c.text
                    .strip_prefix("My project uses ")
                    .filter(|_| c.text.ends_with('.'))
                    .is_some_and(|tail| part == format!("My project is using {tail}"))
        });
        let Some(index) = found else {
            return Ok((None, Some("unpermitted_clause")));
        };
        let clause = remaining.remove(index);
        claims.push(Claim {
            text: part.into(),
            source: clause.source,
            quote: clause.quote,
        });
    }
    let mut seen = BTreeSet::new();
    let evidence_references = claims
        .iter()
        .filter(|c| seen.insert(c.source.clone()))
        .map(|c| c.source.clone())
        .collect();
    let mut content = ModelAnswer {
        answer: answer.into(),
        claims,
        evidence_references,
        opportunity_claims: Vec::new(),
    };
    content.validate()?;
    match grounding::validate(
        &content,
        facts,
        instructions.max_characters,
        instructions.max_words,
        &[],
    )? {
        Some(error) => Ok((None, Some(error))),
        None => Ok((Some(content), None)),
    }
}
