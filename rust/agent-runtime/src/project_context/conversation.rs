//! Read-only approved project preview. Compaction is a preview, never a new verified personal claim.
use super::{Snapshot, approvable, invalid, named};
use crate::{Failure, Result, context_contract::python_space, legacy_regex::Regex};
use automated_apply_domain::text::folded;
use serde_json::{Value, json};
use std::{collections::BTreeSet, sync::LazyLock};
pub(super) fn compact(text: &str, words: usize, characters: usize) -> String {
    let value = text
        .split(python_space)
        .filter(|s| !s.is_empty())
        .take(words)
        .collect::<Vec<_>>()
        .join(" ");
    if value.chars().count() <= characters {
        return value;
    }
    let clipped = value.chars().take(characters).collect::<String>();
    clipped
        .rsplit_once(' ')
        .map(|(head, _)| head.to_owned())
        .unwrap_or(clipped)
}
impl Snapshot {
    pub fn conversation_answer(
        &self,
        question: &str,
        rank: Option<usize>,
        max_words: usize,
        max_characters: usize,
    ) -> Result<Value> {
        if !(1..=2000).contains(&question.chars().count())
            || !(1..=500).contains(&max_words)
            || !(1..=8000).contains(&max_characters)
            || rank.is_some_and(|n| !(1..=30).contains(&n))
        {
            return Err(Failure("invalid_project_conversation_request"));
        }
        let mut projects = vec![];
        for (project, knowledge) in &self.knowledge {
            let candidate = &knowledge["candidate"];
            let approved = &knowledge["approved"];
            if candidate.is_null()
                || approved.is_null()
                || candidate["revision"] != approved["revision"]
                || project != &candidate["configuration"]
            {
                continue;
            }
            if approved["project_id"] != project["id"] {
                return Err(invalid());
            }
            let facts = approved["facts"].as_array().ok_or_else(invalid)?;
            for fact in facts {
                if !approvable(fact)? {
                    return Err(Failure("project_conversation_fact_review_required"));
                }
            }
            projects.push((project, approved, facts.iter().collect::<Vec<_>>()));
        }
        projects.sort_by_key(|(project, _, _)| project["priority"].as_u64());
        if let Some(rank) = rank {
            projects = projects.into_iter().skip(rank - 1).take(1).collect();
        }
        let normalized = named(question);
        let names = self
            .knowledge
            .iter()
            .filter(|(p, _)| {
                p["name"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty() && normalized.contains(&named(s)))
            })
            .map(|(p, _)| p["id"].clone())
            .collect::<Vec<_>>();
        if !names.is_empty() {
            projects.retain(|(project, _, _)| names.contains(&project["id"]));
        }
        static CHALLENGE: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"\b(?:bug|challeng\w*|failure)\b", true));
        static DECISION: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"\b(?:decision|tradeoff|trade-off)\b", true));
        static API: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\bAPIs?\b", true));
        static PERSONAL: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(
                r"\b(?:personally|contribut\w*|integrated|fixed|solved)\b",
                true,
            )
        });
        let topic = if CHALLENGE.is_match(question)? {
            Some("challenge")
        } else if DECISION.is_match(question)? {
            Some("design_decision")
        } else if API.is_match(question)? {
            Some("api")
        } else {
            None
        };
        let personal = matches!(topic, Some("challenge" | "design_decision"))
            || PERSONAL.is_match(question)?;
        if topic.is_some() || personal {
            for (_, _, facts) in &mut projects {
                facts.retain(|f| {
                    topic.is_none_or(|topic| f["topic"] == topic)
                        && (!personal || f["personal_claim"] == true)
                });
            }
            projects.retain(|(_, _, facts)| !facts.is_empty());
        }
        static TERMS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[\w+#.]+", false));
        const STOP: &[&str] = &[
            "describe",
            "explain",
            "tell",
            "what",
            "was",
            "the",
            "a",
            "an",
            "my",
            "your",
            "you",
            "me",
            "about",
            "with",
            "most",
            "important",
            "project",
            "experience",
            "best",
            "built",
            "why",
            "should",
            "we",
            "hire",
        ];
        let terms = TERMS
            .find(&folded(question))?
            .into_iter()
            .map(|m| m.text)
            .filter(|term| !STOP.contains(&term.as_str()))
            .collect::<BTreeSet<_>>();
        let relevance = |facts: &Vec<&Value>| -> usize {
            let text = folded(
                &facts
                    .iter()
                    .filter_map(|f| f["text"].as_str())
                    .collect::<Vec<_>>()
                    .join(" "),
            );
            facts
                .iter()
                .filter(|f| {
                    f["technology"]
                        .as_str()
                        .is_some_and(|s| !s.is_empty() && terms.contains(&folded(s)))
                })
                .count()
                * 3
                + terms
                    .iter()
                    .filter(|term| text.contains(term.as_str()))
                    .count()
        };
        projects.sort_by(|(a, _, af), (b, _, bf)| {
            relevance(bf)
                .cmp(&relevance(af))
                .then_with(|| a["priority"].as_u64().cmp(&b["priority"].as_u64()))
        });
        let Some((_, approval, mut facts)) = projects.into_iter().next() else {
            return Ok(
                json!({"text":compact("No current approved candidate context is available. Review project and resume facts in the dashboard.",max_words,max_characters),"sources":[],"generator":"deterministic_extractive","status":"missing_approved_context"}),
            );
        };
        let matches = |fact: &&Value| {
            let text = folded(fact["text"].as_str().unwrap_or(""));
            terms.iter().filter(|t| text.contains(t.as_str())).count()
        };
        facts.sort_by_key(|fact| std::cmp::Reverse(matches(fact)));
        let text = facts
            .iter()
            .map(|f| f["text"].as_str().ok_or_else(invalid))
            .collect::<Result<Vec<_>>>()?
            .join(" ");
        let sources = json!([{"project_id":approval["project_id"],"revision":approval["revision"],"commit_sha":approval["commit_sha"],"fact_ids":facts.iter().map(|f|f["id"].clone()).collect::<Vec<_>>(),"evidence":facts.iter().flat_map(|f|f["evidence"].as_array().into_iter().flatten().cloned()).collect::<Vec<_>>()}]);
        Ok(
            json!({"text":compact(&text,max_words,max_characters),"sources":sources,"generator":"deterministic_extractive","status":"draft_requires_review"}),
        )
    }
}
