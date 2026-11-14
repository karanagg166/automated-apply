//! Claims are proposals. Exact source quotes, closed provenance and conservative guards decide.
use crate::{
    Failure, Result,
    evidence_retrieval::{bounded, insensitive},
    legacy_regex::Regex,
};
use automated_apply_domain::text::folded;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::LazyLock,
};

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Reference {
    pub source_type: String,
    pub source_id: String,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Claim {
    pub text: String,
    pub source: Reference,
    pub quote: String,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelAnswer {
    pub answer: String,
    pub evidence_references: Vec<Reference>,
    pub claims: Vec<Claim>,
    #[serde(default)]
    pub opportunity_claims: Vec<Claim>,
}
#[derive(Deserialize)]
pub struct Fact {
    pub reference: Reference,
    pub facts: Value,
}
pub(crate) fn whitespace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
pub(crate) fn trim(text: &str) -> &str {
    text.trim_matches(whitespace)
}
pub(crate) fn words(text: &str) -> usize {
    text.split(whitespace).filter(|s| !s.is_empty()).count()
}
fn invalid() -> Failure {
    Failure("invalid_model_answer")
}
fn cleaned(text: &str, max: usize) -> Result<String> {
    let text = text.trim();
    if text.is_empty() || text.chars().count() > max {
        return Err(invalid());
    }
    Ok(text.into())
}
impl Reference {
    pub fn parse(value: Value) -> Result<Self> {
        let mut parsed: Self = serde_json::from_value(value).map_err(|_| invalid())?;
        parsed.validate()?;
        Ok(parsed)
    }
    fn validate(&mut self) -> Result<()> {
        if ![
            "owner_answer",
            "verified_project",
            "verified_role",
            "candidate_evidence",
            "candidate_profile",
            "candidate_preferences",
            "project_context",
            "opportunity_job",
            "opportunity_company",
        ]
        .contains(&self.source_type.as_str())
        {
            return Err(invalid());
        }
        self.source_id = cleaned(&self.source_id, 100)?;
        Ok(())
    }
}
impl ModelAnswer {
    pub fn parse(value: Value) -> Result<Self> {
        let mut parsed: Self = serde_json::from_value(value).map_err(|_| invalid())?;
        parsed.validate()?;
        Ok(parsed)
    }
    pub fn validate(&mut self) -> Result<()> {
        self.answer = cleaned(&self.answer, 10000)?;
        if self.evidence_references.is_empty()
            || self.evidence_references.len() > 12
            || self.claims.is_empty()
            || self.claims.len() > 30
            || self.opportunity_claims.len() > 5
        {
            return Err(invalid());
        }
        for reference in &mut self.evidence_references {
            reference.validate()?;
        }
        for claim in self
            .claims
            .iter_mut()
            .chain(self.opportunity_claims.iter_mut())
        {
            claim.text = cleaned(&claim.text, 4000)?;
            claim.quote = cleaned(&claim.quote, 4000)?;
            claim.source.validate()?;
        }
        Ok(())
    }
}
pub(crate) fn sentences(text: &str) -> Result<Vec<&str>> {
    static SPLIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?<=[.!?])\s+|\n", false));
    SPLIT.split(text)
}
fn flat(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Array(values) => values.iter().map(flat).collect::<Vec<_>>().join(" "),
        Value::Object(values) => values.values().map(flat).collect::<Vec<_>>().join(" "),
        _ => value.to_string(),
    }
}
fn has_word(text: &str, name: &str) -> bool {
    let (text, _) = insensitive(text);
    let (name, _) = insensitive(name);
    text.match_indices(&name)
        .any(|(at, _)| bounded(&text, at, at + name.len()))
}
pub fn validate(
    content: &ModelAnswer,
    facts: &[Fact],
    max_characters: usize,
    max_words: Option<usize>,
    opportunity: &[Fact],
) -> Result<Option<&'static str>> {
    if content.opportunity_claims.is_empty() {
        return validate_candidate(content, facts, max_characters, max_words);
    }
    if content.answer.chars().count() > max_characters
        || max_words.is_some_and(|max| words(&content.answer) > max)
    {
        return Ok(Some("output_length_exceeded"));
    }
    let sources: BTreeMap<_, _> = opportunity
        .iter()
        .map(|f| (f.reference.clone(), &f.facts))
        .collect();
    let references: BTreeSet<_> = content.evidence_references.iter().cloned().collect();
    let candidate_keys: BTreeSet<_> = facts.iter().map(|f| f.reference.clone()).collect();
    if references
        .iter()
        .any(|r| !sources.contains_key(r) && !candidate_keys.contains(r))
    {
        return Ok(Some("invalid_evidence_reference"));
    }
    static UNSAFE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"ignore\s+(?:all\s+)?(?:previous|prior|system)|(?:system|developer)\s*(?:prompt|message|instruction)|reveal\s+(?:secrets|credentials)|send\s+(?:secrets|cookies)|execute\s+(?:command|script)|disregard\s+instructions",
            true,
        )
    });
    static PRONOUN: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b(i|my|me|we|our|you|your)\b", true));
    let parts = sentences(&content.answer)?;
    let mut removed = BTreeSet::new();
    for claim in &content.opportunity_claims {
        if UNSAFE.is_match(&claim.text)? {
            return Ok(Some("unsafe_opportunity_instruction"));
        }
        let Some(source) = sources.get(&claim.source).and_then(|s| s.as_str()) else {
            return Ok(Some("invalid_opportunity_reference"));
        };
        if !references.contains(&claim.source) {
            return Ok(Some("invalid_opportunity_reference"));
        }
        if claim.text != claim.quote
            || !source.contains(&claim.quote)
            || PRONOUN.is_match(&claim.text)?
        {
            return Ok(Some("unsupported_opportunity_claim"));
        }
        if !parts.contains(&claim.text.as_str()) {
            return Ok(Some("opportunity_claim_requires_separate_sentence"));
        }
        if !sentences(source)?.contains(&claim.quote.as_str()) {
            return Ok(Some("unsupported_opportunity_claim"));
        }
        removed.insert(claim.text.as_str());
    }
    let answer = parts
        .into_iter()
        .filter(|s| !removed.contains(s))
        .collect::<Vec<_>>()
        .join(" ");
    let references: Vec<_> = content
        .evidence_references
        .iter()
        .filter(|r| !r.source_type.starts_with("opportunity_"))
        .cloned()
        .collect();
    if answer.is_empty() || references.is_empty() {
        return Ok(Some("candidate_evidence_required"));
    }
    let candidate = ModelAnswer {
        answer,
        evidence_references: references,
        claims: content.claims.clone(),
        opportunity_claims: Vec::new(),
    };
    validate_candidate(&candidate, facts, max_characters, max_words)
}
fn validate_candidate(
    content: &ModelAnswer,
    facts: &[Fact],
    max_characters: usize,
    max_words: Option<usize>,
) -> Result<Option<&'static str>> {
    static PERSON: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(?:I|my)\b", true));
    if !PERSON.is_match(&content.answer)? {
        return Ok(Some("first_person_required"));
    }
    if content.answer.chars().count() > max_characters
        || max_words.is_some_and(|max| words(&content.answer) > max)
    {
        return Ok(Some("output_length_exceeded"));
    }
    let sources: BTreeMap<_, _> = facts
        .iter()
        .map(|f| (f.reference.clone(), flat(&f.facts)))
        .collect();
    let references: BTreeSet<_> = content.evidence_references.iter().cloned().collect();
    if references.is_empty() || references.iter().any(|r| !sources.contains_key(r)) {
        return Ok(Some("invalid_evidence_reference"));
    }
    let selected = references
        .iter()
        .map(|r| sources[r].as_str())
        .collect::<Vec<_>>()
        .join(" ");
    for claim in &content.claims {
        if !references.contains(&claim.source)
            || !folded(&sources[&claim.source]).contains(&folded(&claim.quote))
            || !content.answer.contains(&claim.text)
        {
            return Ok(Some("unsupported_claim"));
        }
    }
    for sentence in sentences(&content.answer)? {
        let sentence = trim(sentence);
        if !sentence.is_empty()
            && !content.claims.iter().any(|claim| {
                claim
                    .text
                    .contains(sentence.trim_end_matches(['.', '!', '?']))
            })
        {
            return Ok(Some("uncited_claim"));
        }
    }
    static NUMBER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b\d[\d,.]*(?:%|[kKmMbB])?\b", false));
    let supported: BTreeSet<_> = NUMBER
        .find(&selected)?
        .into_iter()
        .map(|m| folded(&m.text))
        .collect();
    if NUMBER
        .find(&content.answer)?
        .iter()
        .any(|m| !supported.contains(&folded(&m.text)))
    {
        return Ok(Some("unsupported_number"));
    }
    static NAME: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\b[A-Z][A-Za-z0-9+#]*(?:[.][A-Za-z]+)?\b", false));
    let safe = [
        "i", "my", "the", "a", "an", "at", "in", "for", "this", "it", "we", "to", "using", "by",
    ];
    if NAME
        .find(&content.answer)?
        .iter()
        .any(|m| !safe.contains(&folded(&m.text).as_str()) && !has_word(&selected, &m.text))
    {
        return Ok(Some("unsupported_name"));
    }
    static RISKY: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"\b(?:led|managed|founded|scaled|increased|reduced|improved|optimized|optimised|million|billion|revenue|users|customers|awarded|promoted|passionate|expert|expertise)\b",
            true,
        )
    });
    if RISKY
        .find(&content.answer)?
        .iter()
        .any(|m| !folded(&selected).contains(&folded(&m.text)))
    {
        return Ok(Some("unsupported_accomplishment"));
    }
    static NUMBER_WORD: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)\b",
            true,
        )
    });
    if NUMBER_WORD
        .find(&content.answer)?
        .iter()
        .any(|m| !has_word(&selected, &m.text))
    {
        return Ok(Some("unsupported_number"));
    }
    const CONNECTIVE: &str = "i my me we our a an the and or but with without to of for from on in at by as it its this that these those was were is are be been being have has had do did can could would will used use using built build worked work implemented implement implementation developed develop designed design chose choose needed need wanted want because so then when while after before through during into about also which where how what why one own contribution project solution challenge problem approach role involved focused focus helped help allowed allow made make keep kept rather than together explain part responsible personally specifically technical engineering purpose main decision decisions experience request requests service application backend";
    fn stem(word: &str) -> String {
        for suffix in ["ing", "ed", "es", "s"] {
            if word.ends_with(suffix) && word.len() > suffix.len() + 3 {
                return word[..word.len() - suffix.len()].into();
            }
        }
        word.into()
    }
    static ASCII: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new("[a-z]+").unwrap());
    let mut supported: BTreeSet<_> = ASCII
        .find_iter(&folded(&selected))
        .map(|m| stem(m.as_str()))
        .collect();
    supported.extend(CONNECTIVE.split(' ').map(stem));
    if ASCII
        .find_iter(&folded(&content.answer))
        .any(|m| !supported.contains(&stem(m.as_str())))
    {
        return Ok(Some("unsupported_claim"));
    }
    Ok(None)
}
