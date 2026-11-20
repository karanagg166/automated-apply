//! Approve an exact selection from the current stored candidate and retain prior evidence.

use super::{
    CONFIGURATION_KEY, configuration_record, digest, invalid, key, lock_record, next_revision,
    save, timestamp,
};
use crate::{
    Failure, Result,
    context_contract::{Kind, normalize},
};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::{HashMap, HashSet};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Input {
    expected_revision: String,
    fact_ids: Vec<String>,
    owner_confirmed: bool,
}

impl Input {
    pub(super) fn parse(body: &[u8]) -> Result<Self> {
        let invalid = Failure("invalid_project_context_request");
        let input: Self = serde_json::from_slice(body).map_err(|_| invalid)?;
        if !(1..=120).contains(&input.expected_revision.chars().count())
            || !(1..=100).contains(&input.fact_ids.len())
        {
            return Err(invalid);
        }
        if !input.owner_confirmed {
            return Err(Failure("explicit_owner_review_required"));
        }
        Ok(input)
    }
}

pub(super) async fn approve(
    tx: &mut Transaction<'_, Postgres>,
    id: &str,
    input: Input,
) -> Result<Value> {
    let stale = Failure("project_changed_rebuild_and_review");
    let configuration = lock_record(tx, CONFIGURATION_KEY).await?.ok_or(stale)?;
    let configuration = configuration_record(Some(configuration))?;
    let project = configuration["configuration"]["projects"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|project| project["id"] == id)
        .ok_or(stale)?;
    let record_key = key(project)?;
    let stored = lock_record(tx, &record_key).await?.ok_or(stale)?;
    let mut knowledge = normalize(Kind::Knowledge, stored.clone())?;
    let candidate = &knowledge["candidate"];
    if candidate["revision"].as_str() != Some(input.expected_revision.as_str())
        || &candidate["configuration"] != project
    {
        return Err(stale);
    }

    let mut seen = HashSet::new();
    let selected: Vec<_> = input
        .fact_ids
        .iter()
        .filter(|id| seen.insert(id.as_str()))
        .collect();
    let mut indexed = HashMap::new();
    for fact in candidate["facts"].as_array().ok_or_else(invalid)? {
        let id = fact["id"].as_str().ok_or_else(invalid)?;
        if indexed.insert(id, fact).is_some() {
            return Err(invalid());
        }
    }
    let mut facts = Vec::with_capacity(selected.len());
    for id in &selected {
        let fact = *indexed
            .get(id.as_str())
            .ok_or(Failure("fact_selection_not_in_current_revision"))?;
        if !super::super::approvable(fact)? {
            return Err(Failure("inferred_or_unevidenced_claim_cannot_be_approved"));
        }
        facts.push(fact);
    }
    let prior = knowledge["approved"].clone();
    if !prior.is_null() && prior["project_id"] != id {
        return Err(invalid());
    }
    if prior["revision"] == input.expected_revision && prior["fact_ids"] == json!(selected) {
        return Ok(prior);
    }

    let at = timestamp(tx).await?;
    let approved = json!({"project_id":id,"revision":candidate["revision"],"commit_sha":candidate["commit_sha"],
        "fact_ids":selected,"owner_ref":"owner","approved_at":at,"facts":facts,
        "contexts":contexts(&facts),"status":"approved"});
    let event = json!({"kind":"project_context_approved","before_hash":digest(&prior),
        "after_hash":digest(&approved),"actor_ref":"owner","created_at":at});
    let revision = next_revision(&knowledge)?;
    if knowledge["history"].as_array().ok_or_else(invalid)?.len() >= 50
        || knowledge["audits"].as_array().ok_or_else(invalid)?.len() >= 100
    {
        return Err(Failure("project_history_archive_required"));
    }
    if !prior.is_null() {
        knowledge["history"]
            .as_array_mut()
            .ok_or_else(invalid)?
            .push(prior);
    }
    knowledge["audits"]
        .as_array_mut()
        .ok_or_else(invalid)?
        .push(event);
    knowledge["revision"] = json!(revision);
    knowledge["approved"] = approved.clone();
    let knowledge = normalize(Kind::Knowledge, knowledge)?;
    save(tx, &record_key, Some(&stored), &knowledge).await?;
    Ok(approved)
}

fn contexts(facts: &[&Value]) -> Value {
    use super::super::conversation::compact;

    let text = |topics: &[&str]| {
        facts
            .iter()
            .filter(|fact| {
                fact["topic"]
                    .as_str()
                    .is_some_and(|topic| topics.contains(&topic))
            })
            .filter_map(|fact| fact["text"].as_str())
            .collect::<Vec<_>>()
            .join(" ")
    };
    let overview = text(&["overview", "business_use_case", "feature", "contribution"]);
    let technical = text(&[
        "architecture",
        "frontend",
        "backend",
        "database",
        "cache",
        "queue",
        "authentication_security",
        "deployment",
        "api",
        "design_decision",
    ]);
    let stack = text(&["technology"]);
    let base = [&overview, &technical, &stack]
        .into_iter()
        .find(|value| !value.is_empty())
        .map_or("", String::as_str);
    let interview = text(&["interview", "contribution", "challenge"]);
    let bullets = facts
        .iter()
        .filter(|f| {
            matches!(
                f["topic"].as_str(),
                Some("contribution" | "feature" | "measured_outcome")
            )
        })
        .filter_map(|f| f["text"].as_str())
        .take(5)
        .map(|text| compact(text, 35, 240))
        .collect::<Vec<_>>();
    json!({"overview_50":compact(base, 50, 2000),"explanation_100":compact(base, 100, 2000),
        "architecture":compact(&technical, 100, 2000),"technology_stack":compact(&stack, 100, 2000),
        "engineering_challenges":compact(&text(&["challenge"]), 100, 2000),
        "interview_explanation":compact(if interview.is_empty() { base } else { &interview }, 100, 2000),
        "resume_bullet_candidates":bullets,"fact_ids":facts.iter().map(|fact| &fact["id"]).collect::<Vec<_>>(),
        "generator":"deterministic_extractive"})
}
