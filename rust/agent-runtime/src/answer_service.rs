//! Existing generation lifecycle on one caller-owned connection, with no Python runtime.
//! Callers must keep owner control handling independent when optional inference is enabled.
use crate::{
    Failure, Result,
    answer_context::{self, Stamp},
    answer_contract::{self, Generate},
    answer_direct::{self, Limits},
    configuration::boolean,
    evidence_retrieval, extractive,
    grounding::{self, Fact},
    job_context::Reviewed,
    missing_contract, missing_store, profile_store, project_context,
    provider::CohereModel,
    question_classifier, resource_store,
};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::BTreeMap;
use uuid::Uuid;

pub struct Settings {
    pub(crate) defaults: BTreeMap<String, String>,
    pub(crate) opportunity: bool,
    pub(crate) reuse: bool,
    writing: Option<Writer>,
    provider: &'static str,
    model: Option<String>,
    unavailable: Failure,
}
enum Writer {
    Cohere(CohereModel),
    Gemini(crate::gemini::GeminiModel),
    Ollama(crate::ollama::OllamaModel),
}
impl Settings {
    pub(crate) fn share_gate(&mut self, gate: std::sync::Arc<tokio::sync::Semaphore>) {
        if let Some(model) = &mut self.writing {
            match model {
                Writer::Cohere(model) => model.share_gate(gate),
                Writer::Gemini(model) => model.gate = gate,
                Writer::Ollama(model) => model.gate = gate,
            }
        }
    }
    pub fn from_values(
        values: &BTreeMap<String, String>,
        fixture: bool,
        defaults: BTreeMap<String, String>,
    ) -> Result<Self> {
        let name = values
            .get("LLM_PROVIDER")
            .map(String::as_str)
            .unwrap_or("gemini");
        let (provider, key) = match name {
            "cohere" => ("cohere", "COHERE_MODEL"),
            "gemini" => ("gemini", "LLM_MODEL"),
            "ollama" => ("ollama", "OLLAMA_MODEL"),
            "agy" => ("agy", "AGY_MODEL"),
            _ => return Err(Failure("unsupported_provider")),
        };
        let model = values.get(key).filter(|s| !s.trim().is_empty()).cloned();
        if model
            .as_ref()
            .is_some_and(|s| s.len() > 200 || s.chars().any(char::is_control))
        {
            return Err(Failure("invalid_provider_configuration"));
        }
        let mut out = Self {
            defaults,
            opportunity: boolean(values, "OPPORTUNITY_CONTEXT_ENABLED", false)?,
            reuse: boolean(values, "APPROVED_ANSWER_REUSE_ENABLED", false)?,
            writing: None,
            provider,
            model,
            unavailable: Failure("llm_not_configured"),
        };
        if provider == "cohere" && out.model.is_some() {
            if !boolean(values, "COHERE_ENABLED", false)? {
                out.unavailable = Failure("provider_permission_required");
            } else {
                let mut selected = values.clone();
                selected.insert("RUST_AGENT_REVIEW_MODEL".into(), "cohere".into());
                match CohereModel::runtime(&selected, fixture) {
                    Ok(model) => out.writing = model.map(Writer::Cohere),
                    Err(error) => out.unavailable = error,
                }
            }
        } else if provider == "ollama" {
            match crate::ollama::OllamaModel::from_values(values, fixture) {
                Ok(model) => out.writing = Some(Writer::Ollama(model)),
                Err(error) => out.unavailable = error,
            }
        } else if provider == "agy" {
            out.unavailable = Failure("provider_execution_not_authorized");
        } else if provider == "gemini" {
            match crate::gemini::GeminiModel::from_values(values, fixture) {
                Ok(model) => out.writing = Some(Writer::Gemini(model)),
                Err(error) => out.unavailable = error,
            }
        }
        Ok(out)
    }
}
fn db(error: sqlx::Error) -> Failure {
    if error
        .as_database_error()
        .is_some_and(|e| matches!(e.code().as_deref(), Some("40001" | "40P01")))
    {
        Failure("generation_context_changed")
    } else {
        Failure("profile_database_error")
    }
}
async fn begin(connection: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    Ok(tx)
}
fn failure(category: &str, style: &str, code: Failure) -> Value {
    let mut out = answer_contract::result(category, style);
    out["status"] = json!("validation_failed");
    out["error_code"] = json!(code.0);
    out
}
fn missing(category: &str) -> &'static str {
    match category {
        "project_explanation" | "technical_experience" => {
            "Describe a relevant project's purpose, your actual contribution, implementation details, and (if asked) its engineering challenge and solution; confirm this evidence"
        }
        "motivation" | "startup_interest" => {
            "Save your actual role, industry, technology or company-stage preferences explaining why this opportunity interests you"
        }
        _ => "Supply a reviewed professional summary or career evidence relevant to this question",
    }
}
struct Writing {
    request: Generate,
    stamp: Stamp,
    facts: Vec<Fact>,
    opportunity: Vec<Fact>,
    context: Value,
    instructions: Value,
    category: &'static str,
    limits: Limits,
}
enum Prepared {
    Ready { request: Generate, result: Value },
    Writing(Box<Writing>),
}
async fn prepare(
    tx: &mut Transaction<'_, Postgres>,
    mut request: Generate,
    settings: &Settings,
) -> Result<Prepared> {
    // A primary correction cannot commit while this local preparation/draft save is in flight.
    let owned: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let id = owned.ok_or(Failure("profile_not_found"))?;
    let profile = profile_store::get(tx).await?;
    let mut opportunity = vec![];
    if let Some(id) = request.job_id {
        let job = Reviewed::load_in(tx, id)
            .await?
            .ok_or(Failure("job_not_found"))?;
        request = match job.bind_request(&request) {
            Ok(request) => request,
            Err(error) => {
                let mut result = failure("unknown", "professional", error);
                result["missing_information"] = json!([if error.0 == "company_context_mismatch" {
                    "Requested company does not match the saved job; correct the context before generation"
                } else {
                    "Requested description differs from the saved job; update and review that job first"
                }]);
                return Ok(Prepared::Ready { request, result });
            }
        };
        if settings.opportunity {
            let now: f64 =
                sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8")
                    .fetch_one(&mut **tx)
                    .await
                    .map_err(db)?;
            opportunity = job.opportunity(now)?;
            if request
                .job_description
                .as_ref()
                .is_none_or(String::is_empty)
                && !opportunity.is_empty()
            {
                request.job_description = opportunity[0]["facts"].as_str().map(String::from);
            }
        }
    }
    let limits = Limits::for_request(&request)?;
    if let Some(approved) = missing_store::approved_in(tx, &request).await? {
        let mut result = answer_contract::result(
            approved["question_category"]
                .as_str()
                .ok_or(Failure("invalid_missing_input_record"))?,
            "professional",
        );
        result["answer"] = approved["answer"].clone();
        result = limits.enforce(result);
        if result["answer"].is_null() {
            return Ok(Prepared::Ready { request, result });
        }
        result["source"] = json!("owner_approved_exact_context");
        result["confidence"] = json!(1.0);
        result["status"] = json!("draft_ready");
        result["requires_review"] = json!(false);
        result["draft_id"] = approved["draft_id"].clone();
        result["missing_input_id"] = approved["id"].clone();
        result["missing_input_url"] = approved["href"].clone();
        result["evidence_references"] =
            json!([{"source_type":"owner_answer","source_id":approved["id"]}]);
        return Ok(Prepared::Ready { request, result });
    }
    let resources = resource_store::resolution_resources(tx, id).await?;
    if let Some(result) =
        answer_direct::resolve(&profile.value, &resources, &settings.defaults, &request)?
    {
        return Ok(Prepared::Ready { request, result });
    }
    let category = question_classifier::classify(&request.question).question_type;
    let evidence = answer_context::relevant_evidence(tx, id, &request.question).await?;
    let mut facts = serde_json::to_value(evidence_retrieval::retrieve(
        &profile.value,
        &evidence,
        &request.question,
        category,
    )?)
    .map_err(|_| Failure("invalid_verified_context"))?
    .as_array()
    .cloned()
    .ok_or(Failure("invalid_verified_context"))?;
    let project_snapshot = project_context::Snapshot::load_in(tx).await?;
    let projects = project_snapshot.answer_evidence(&request.question, category)?;
    let has_project_facts = !projects.is_empty();
    if has_project_facts {
        facts = projects;
    }
    if !opportunity.is_empty() && matches!(category, "motivation" | "startup_interest") {
        let work = evidence_retrieval::retrieve(
            &profile.value,
            &evidence,
            request
                .job_description
                .as_deref()
                .unwrap_or(&request.question),
            "project_explanation",
        )?;
        let targets = evidence_retrieval::tokens(
            &opportunity
                .iter()
                .filter_map(|v| v["facts"].as_str())
                .collect::<Vec<_>>()
                .join(" "),
        );
        let work = work
            .into_iter()
            .filter(|v| !targets.is_disjoint(&evidence_retrieval::tokens(&v.facts.to_string())))
            .take(3)
            .collect::<Vec<_>>();
        if work.is_empty() {
            facts.clear();
        } else {
            for item in work {
                facts.push(
                    serde_json::to_value(item).map_err(|_| Failure("invalid_verified_context"))?,
                );
            }
        }
    }
    let mut result = answer_contract::result(category, &request.writing_style);
    if facts.is_empty() {
        result["missing_information"] = json!([missing(category)]);
        return Ok(Prepared::Ready { request, result });
    }
    if matches!(category, "motivation" | "startup_interest")
        && (request.company_name.is_none() || request.job_description.is_none())
    {
        result["missing_information"] = json!([
            "Supply company_name and job_description, plus saved preferences explaining your interest"
        ]);
        return Ok(Prepared::Ready { request, result });
    }
    if settings.reuse
        && let Some(result) = crate::answer_reuse::reuse_in(
            tx,
            &profile.value,
            &request,
            category,
            limits,
            settings.opportunity,
        )
        .await?
    {
        return Ok(Prepared::Ready { request, result });
    }
    let context = json!({"evidence":facts});
    let instruction = extractive::Instructions {
        max_characters: limits.characters,
        max_words: limits.words,
    };
    let prepared = extractive::prepare(&request.question, &context, instruction)?;
    if !prepared.missing.is_empty() {
        result["missing_information"] = json!(prepared.missing);
        result["source"] = json!("needs_input");
    } else if let Some(code) = prepared.error {
        result = failure(category, &request.writing_style, Failure(code));
        result["source"] = json!("validation_failed");
    } else {
        let text = prepared
            .clauses
            .iter()
            .map(|c| c.text.as_str())
            .collect::<Vec<_>>()
            .join(" ");
        let facts: Vec<Fact> = serde_json::from_value(json!(facts))
            .map_err(|_| Failure("invalid_verified_context"))?;
        let (content, error) = extractive::match_answer(&text, &prepared, &facts, instruction)?;
        if let Some(error) = error {
            result = failure(category, &request.writing_style, Failure(error));
            result["source"] = json!("validation_failed");
        } else if let Some(content) = content {
            result["answer"] = json!(content.answer);
            result["status"] = json!("draft_ready");
            result["source"] = json!("deterministic_extractive");
            result["evidence_references"] = json!(content.evidence_references);
            result["warnings"] = json!(["Extracted approved facts; review before use."]);
        }
    }
    if !request.rewrite
        || (result["answer"].is_null()
            && (opportunity.is_empty() || !result["error_code"].is_null()))
    {
        return Ok(Prepared::Ready { request, result });
    }
    let stamp = Stamp::load_in(tx, &request).await?;
    let facts: Vec<Fact> =
        serde_json::from_value(json!(facts)).map_err(|_| Failure("invalid_verified_context"))?;
    let opportunity_facts: Vec<Fact> = serde_json::from_value(json!(opportunity))
        .map_err(|_| Failure("invalid_verified_context"))?;
    let style = match request.writing_style.as_str() {
        "professional" => "Clear, direct first-person professional prose.",
        "conversational" => {
            "Natural, straightforward first-person language without corporate cliches."
        }
        "technical" => {
            "Explain documented implementation decisions, challenges and their solutions precisely."
        }
        "concise" => "Use the fewest words needed to answer specifically.",
        _ => {
            "Emphasize documented personal ownership, problem and solution without invented business impact."
        }
    };
    let instructions = json!({"opportunity_evidence":crate::job_context::prompt_opportunity(&opportunity),"style_instruction":style,"max_characters":limits.characters,"max_words":limits.words,"job_context":{"company_name":request.company_name,"job_description":request.job_description}});
    // Full local provenance binds validation; provider payloads omit project URLs/files.
    let context = if has_project_facts {
        json!({"evidence":project_snapshot.prompt_evidence(&request.question,category)?})
    } else {
        context
    };
    Ok(Prepared::Writing(Box::new(Writing {
        request,
        stamp,
        facts,
        opportunity: opportunity_facts,
        context,
        instructions,
        category,
        limits,
    })))
}
async fn finish(
    tx: &mut Transaction<'_, Postgres>,
    request: &Generate,
    mut result: Value,
    preserve_rollback: bool,
) -> Result<Value> {
    if request.save_draft
        && result["status"] == "draft_ready"
        && result["answer"].as_str().is_some_and(|s| !s.is_empty())
        && result["reused_draft_id"].is_null()
        && result["source"] != "owner_approved_exact_context"
    {
        let profile = profile_store::get(tx).await?;
        let id = Uuid::new_v4();
        let owner: Uuid = profile.value["id"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .ok_or(Failure("invalid_profile_record"))?;
        let row:Value=sqlx::query_scalar("INSERT INTO application_answer_drafts(id,candidate_profile_id,job_id,question,answer,question_category,writing_style,evidence_references,candidate_profile_version,review_status,provider,model,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'draft',$10,$11,clock_timestamp(),clock_timestamp()) RETURNING to_jsonb(application_answer_drafts.*)").bind(id).bind(owner).bind(request.job_id).bind(&request.question).bind(result["answer"].as_str().unwrap()).bind(result["question_type"].as_str().unwrap()).bind(&request.writing_style).bind(&result["evidence_references"]).bind(profile.version).bind(result["provider"].as_str()).bind(result["model"].as_str()).fetch_one(&mut **tx).await.map_err(db)?;
        crate::answer_store::record(row.clone(), profile.version)?;
        if row["id"] != json!(id)
            || row["candidate_profile_id"] != json!(owner)
            || row["job_id"] != json!(request.job_id)
            || row["question"] != request.question
            || row["answer"] != result["answer"]
            || row["review_status"] != "draft"
        {
            return Err(Failure("answer_draft_context_mismatch"));
        }
        result["draft_id"] = json!(id);
    }
    if result["status"] == "needs_input"
        && result["answer"].is_null()
        && missing_contract::permitted(&request.question, "").is_ok()
    {
        let input = missing_contract::Create {
            request: request.clone(),
            packet_id: None,
            missing_fact: result["missing_information"]
                .as_array()
                .and_then(|v| v.first())
                .and_then(Value::as_str)
                .unwrap_or("Provide a verified fact")
                .into(),
            reason: "Answer generation stopped because approved evidence is missing".into(),
            required_input_type: "evidence".into(),
        };
        let id = if preserve_rollback {
            missing_store::ensure_retryable_in(tx, &input)
                .await
                .map_err(|error| {
                    if error == Failure("missing_input_transaction_rollback") {
                        Failure("packet_serialization_rollback")
                    } else {
                        error
                    }
                })?
        } else {
            missing_store::ensure_in(tx, &input).await?
        };
        result["missing_input_id"] = json!(id);
        result["missing_input_url"] = json!(format!("/api/v1/application-answers/missing/{id}"));
    }
    Ok(result)
}
pub async fn generate(
    connection: &mut PgConnection,
    input: Value,
    settings: &Settings,
) -> Result<Value> {
    let request = answer_contract::normalize(input)?;
    let mut tx = begin(connection).await?;
    let writing = match prepare(&mut tx, request, settings).await? {
        Prepared::Ready { request, result } => {
            let result = finish(&mut tx, &request, result, false).await?;
            tx.commit().await.map_err(db)?;
            return Ok(result);
        }
        Prepared::Writing(writing) => writing,
    };
    // No profile/evidence locks or read transaction survive a provider wait.
    tx.commit().await.map_err(db)?;
    let mut result = answer_contract::result(writing.category, &writing.request.writing_style);
    result["provider"] = json!(settings.provider);
    result["model"] = json!(settings.model);
    let Some(provider) = &settings.writing else {
        result["status"] = json!("provider_unavailable");
        result["error_code"] = json!(settings.unavailable.0);
        if matches!(
            settings.unavailable.0,
            "llm_not_configured" | "unsupported_provider"
        ) {
            result["missing_information"] = json!([
                "Enable a configured local Ollama model or an independently authorized remote provider to generate narrative drafts"
            ]);
        }
        return Ok(result);
    };
    let call = match provider {
        Writer::Cohere(provider) => {
            provider
                .write_answer(
                    connection,
                    &writing.request.question,
                    &writing.context,
                    &writing.instructions,
                )
                .await
        }
        Writer::Gemini(provider) => {
            provider
                .write_answer(
                    connection,
                    &writing.request.question,
                    &writing.context,
                    &writing.instructions,
                )
                .await
        }
        Writer::Ollama(provider) => {
            provider
                .write_answer(
                    connection,
                    &writing.request.question,
                    &writing.context,
                    &writing.instructions,
                )
                .await
        }
    };
    result["used_llm"] = json!(call.attempted);
    if call.input.is_some() || call.output.is_some() || call.content.is_some() {
        result["usage"] = json!({"input_tokens":call.input,"output_tokens":call.output});
    }
    if let Some(error) = call.error {
        result["status"] = json!(if error.0 == "invalid_structured_response" {
            "validation_failed"
        } else {
            "provider_unavailable"
        });
        result["error_code"] = json!(error.0);
        if let Some(seconds) = call.retry_after {
            result["retry_after_seconds"] = json!(seconds as f64);
        }
        return Ok(result);
    }
    let content = call.content.ok_or(Failure("invalid_structured_response"))?;
    let mut tx = begin(connection).await?;
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    if Stamp::load_in(&mut tx, &writing.request)
        .await?
        .generation()
        != writing.stamp.generation()
    {
        result["status"] = json!("validation_failed");
        result["error_code"] = json!("generation_context_changed");
        result["missing_information"] = json!([
            "Approved facts or job context changed during generation; reload and review before generating again"
        ]);
    } else if !writing.opportunity.is_empty()
        && (content.opportunity_claims.is_empty()
            || !content.evidence_references.iter().any(|r| {
                matches!(
                    r.source_type.as_str(),
                    "verified_project" | "verified_role" | "candidate_evidence"
                )
            }))
    {
        result["status"] = json!("validation_failed");
        result["error_code"] = json!("company_and_candidate_evidence_required");
    } else if let Some(error) = grounding::validate(
        &content,
        &writing.facts,
        writing.limits.characters,
        writing.limits.words,
        &writing.opportunity,
    )? {
        result["status"] = json!("validation_failed");
        result["error_code"] = json!(error);
    } else {
        result["status"] = json!("draft_ready");
        result["answer"] = json!(content.answer);
        result["evidence_references"] = json!(content.evidence_references);
        result["warnings"] = json!([
            "Factual checks are conservative safeguards, not verification; review every narrative claim"
        ]);
    }
    let result = finish(&mut tx, &writing.request, result, false).await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}

/// Packet preparation can resolve facts and persist missing questions in its own
/// transaction. It never commits, saves narrative drafts or dispatches inference.
pub(crate) async fn factual_in(
    tx: &mut Transaction<'_, Postgres>,
    request: Generate,
    settings: &Settings,
) -> Result<Value> {
    if request.rewrite
        || request.save_draft
        || matches!(
            question_classifier::classify(&request.question).question_type,
            "project_explanation"
                | "technical_experience"
                | "short_text"
                | "motivation"
                | "startup_interest"
        )
    {
        return Err(Failure("packet_explicit_generation_required"));
    }
    match prepare(tx, request, settings).await? {
        Prepared::Ready { request, result } => finish(tx, &request, result, true).await,
        Prepared::Writing(_) => Err(Failure("packet_explicit_generation_required")),
    }
}
/// Explicit form inspection can extract a reviewable narrative, but never waits on a model.
/// Uses the caller's serializable transaction so draft/missing-input writes roll back together.
pub(crate) async fn form_in(
    tx: &mut Transaction<'_, Postgres>,
    request: Generate,
    settings: &Settings,
) -> Result<Value> {
    if request.rewrite {
        return Err(Failure("form_rewrite_not_authorized"));
    }
    match prepare(tx, request, settings).await? {
        Prepared::Ready { request, result } => finish(tx, &request, result, true).await,
        Prepared::Writing(_) => Err(Failure("form_rewrite_not_authorized")),
    }
}
