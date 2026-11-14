//! Exact supported narrative intent, private fingerprints and signed owner reuse grants.
use crate::{
    Failure, Result,
    answer_context::Stamp,
    answer_contract::{self, Generate},
    answer_direct::Limits,
    context_contract,
    evidence_retrieval::bounded,
    grounding::{self, Reference},
    job_context::Reviewed,
    link_resolver::normalize,
    owner_proof::Proof,
    profile_store, project_context, question_classifier,
};
use automated_apply_domain::text::folded;
use regex::Regex;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::{collections::BTreeSet, sync::LazyLock};
use uuid::Uuid;
const NARRATIVES: &[&str] = &[
    "project_explanation",
    "technical_experience",
    "short_text",
    "motivation",
    "startup_interest",
];
const WORDS: &str = "describe explain tell us me about your you my i a an the of and or to in with using used use built build developed develop implemented implement created create made make have has how what why most best biggest technically technical engineering challenging challenge challenges difficult difficulty problem problems solved solve solution solutions project projects application applications tool tools work worked experience contribution contributions purpose does it do impressive thing proud proudest are is which interests interest interested join joining want would like company role startup yourself professional summary short bio introduce for this our";
pub fn semantic_intent(question: &str, category: &str, profile: &Value) -> Result<Option<Value>> {
    if !NARRATIVES.contains(&category) {
        return Ok(None);
    }
    if question.chars().count() > 2000 {
        return Err(Failure("invalid_answer_request"));
    }
    let q = normalize(question_classifier::canonical(question).unwrap_or(question));
    let mut skills = vec![];
    for value in profile["verified_skills"]
        .as_array()
        .ok_or(Failure("invalid_profile_record"))?
    {
        let value = folded(value.as_str().ok_or(Failure("invalid_profile_record"))?);
        if !value.is_empty()
            && q.match_indices(&value)
                .any(|(at, _)| bounded(&q, at, at + value.len()))
        {
            skills.push(value);
        }
    }
    skills.sort();
    let mut projects = vec![];
    for value in profile["projects"]
        .as_array()
        .ok_or(Failure("invalid_profile_record"))?
    {
        let value = folded(
            value["name"]
                .as_str()
                .ok_or(Failure("invalid_profile_record"))?,
        );
        if q.contains(&value) {
            projects.push(value);
        }
    }
    projects.sort();
    static TOKENS: LazyLock<Regex> = LazyLock::new(|| Regex::new("[a-z]+").unwrap());
    let entities = skills
        .iter()
        .chain(&projects)
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    let entity_words: BTreeSet<_> = TOKENS.find_iter(&entities).map(|m| m.as_str()).collect();
    if TOKENS.find_iter(&q).any(|m| {
        !WORDS.split(' ').any(|word| word == m.as_str()) && !entity_words.contains(m.as_str())
    }) {
        return Ok(None);
    }
    static CHALLENGE: LazyLock<crate::legacy_regex::Regex> = LazyLock::new(|| {
        crate::legacy_regex::Regex::new(r"\b(challeng\w*|difficult\w*|problem|solv\w*)\b", false)
    });
    let intent = if matches!(category, "motivation" | "startup_interest") {
        "company_motivation"
    } else if category == "short_text" {
        "professional_summary"
    } else if CHALLENGE.is_match(&q)? {
        "engineering_challenge"
    } else if category == "technical_experience" {
        "technical_usage"
    } else {
        "project_overview"
    };
    Ok(Some(
        json!({"intent":intent,"skills":skills,"projects":projects}),
    ))
}
pub fn draft_digest(draft: &Value) -> Result<String> {
    if !draft.is_object()
        || [
            "question",
            "answer",
            "question_category",
            "writing_style",
            "evidence_references",
            "job_id",
        ]
        .iter()
        .any(|k| draft.get(*k).is_none())
    {
        return Err(Failure("invalid_answer_draft_record"));
    }
    let job = if draft["job_id"].is_null() {
        "None".to_owned()
    } else {
        draft["job_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_answer_draft_record"))?
            .to_string()
    };
    Ok(crate::python_json::digest(
        &json!({"question":draft["question"],"answer":draft["answer"],"category":draft["question_category"],"style":draft["writing_style"],"references":draft["evidence_references"],"job_id":job}),
    ))
}
pub struct Approve {
    pub expected_profile_version: u64,
    pub scope: String,
    pub confirmed: bool,
}
pub fn approval_input(input: Value) -> Result<Approve> {
    let bad = || Failure("invalid_answer_reuse_approval");
    let body = input.as_object().ok_or_else(bad)?;
    if body.len() != 3
        || body.keys().any(|s| {
            ![
                "expected_profile_version",
                "scope",
                "confirm_reviewed_answer",
            ]
            .contains(&s.as_str())
        })
    {
        return Err(bad());
    }
    let version = context_contract::integer(body["expected_profile_version"].clone())
        .map_err(|_| bad())?
        .as_u64()
        .filter(|v| *v > 0)
        .ok_or_else(bad)?;
    let scope = grounding::trim(body["scope"].as_str().ok_or_else(bad)?);
    if !["same_job", "general_profile"].contains(&scope) {
        return Err(bad());
    }
    let confirmed = body["confirm_reviewed_answer"].as_bool().ok_or_else(bad)?;
    Ok(Approve {
        expected_profile_version: version,
        scope: scope.into(),
        confirmed,
    })
}
fn db(error: sqlx::Error) -> Failure {
    if error
        .as_database_error()
        .is_some_and(|e| matches!(e.code().as_deref(), Some("40001" | "40P01")))
    {
        Failure("answer_reuse_context_changed")
    } else {
        Failure("profile_database_error")
    }
}
async fn begin(
    connection: &mut PgConnection,
    read_only: bool,
) -> Result<Transaction<'_, Postgres>> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query(if read_only {
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    } else {
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
    })
    .execute(&mut *tx)
    .await
    .map_err(db)?;
    Ok(tx)
}
fn request(draft: &Value) -> Result<Generate> {
    answer_contract::normalize(json!({"question":draft["question"],"job_id":draft["job_id"]}))
}
fn references(draft: &Value) -> Result<Vec<Reference>> {
    draft["evidence_references"]
        .as_array()
        .ok_or(Failure("invalid_answer_draft_record"))?
        .iter()
        .cloned()
        .map(Reference::parse)
        .collect()
}
async fn current_references(
    tx: &mut Transaction<'_, Postgres>,
    draft: &Value,
    request: &Generate,
    opportunity_enabled: bool,
) -> Result<bool> {
    let references = references(draft)?;
    if references
        .iter()
        .any(|r| r.source_type.starts_with("opportunity_"))
    {
        if !opportunity_enabled {
            return Ok(false);
        }
        let Some(job) = request.job_id else {
            return Ok(false);
        };
        let Some(job) = Reviewed::load_in(tx, job).await? else {
            return Ok(false);
        };
        let now: f64 = sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8")
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
        let facts = job.opportunity(now)?;
        if references
            .iter()
            .filter(|r| r.source_type.starts_with("opportunity_"))
            .any(|r| !facts.iter().any(|f| f["reference"] == json!(r)))
        {
            return Ok(false);
        }
    }
    if references
        .iter()
        .any(|r| r.source_type == "project_context")
    {
        let category = question_classifier::classify(&request.question).question_type;
        let facts = project_context::Snapshot::load_in(tx)
            .await?
            .answer_evidence(&request.question, category)?;
        if references
            .iter()
            .filter(|r| r.source_type == "project_context")
            .any(|r| !facts.iter().any(|f| f["reference"] == json!(r)))
        {
            return Ok(false);
        }
    }
    Ok(true)
}
pub async fn approve(
    connection: &mut PgConnection,
    id: Uuid,
    input: Approve,
    proof: Proof,
    enabled: bool,
    opportunity_enabled: bool,
) -> Result<Value> {
    if !enabled {
        return Err(Failure("answer_reuse_disabled"));
    }
    if input.expected_profile_version == 0
        || !["same_job", "general_profile"].contains(&input.scope.as_str())
    {
        return Err(Failure("invalid_answer_reuse_approval"));
    }
    let mut tx = begin(connection, false).await?;
    let owner: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let owner = owner.ok_or(Failure("profile_not_found"))?;
    let profile = profile_store::get(&mut tx).await?;
    let draft:Value=sqlx::query_scalar("SELECT to_jsonb(d) FROM application_answer_drafts d WHERE id=$1 AND candidate_profile_id=$2 FOR UPDATE").bind(id).bind(owner).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("answer_draft_not_found"))?;
    crate::answer_store::record(draft.clone(), profile.version)?;
    if !input.confirmed
        || draft["review_status"] != "reviewed"
        || u64::try_from(profile.version).ok() != Some(input.expected_profile_version)
        || draft["candidate_profile_version"] != profile.version
    {
        return Err(Failure("answer_reuse_current_review_required"));
    }
    let category = draft["question_category"]
        .as_str()
        .ok_or(Failure("invalid_answer_draft_record"))?;
    let intent = semantic_intent(
        draft["question"].as_str().unwrap(),
        category,
        &profile.value,
    )?
    .ok_or(Failure("answer_reuse_unsupported_intent"))?;
    if input.scope == "same_job" && draft["job_id"].is_null() {
        return Err(Failure("answer_reuse_job_required"));
    }
    let refs = references(&draft)?;
    if input.scope == "general_profile"
        && (intent["intent"] == "company_motivation"
            || refs
                .iter()
                .any(|r| r.source_type.starts_with("opportunity_")))
    {
        return Err(Failure("answer_reuse_exact_job_required"));
    }
    let req = request(&draft)?;
    if !current_references(&mut tx, &draft, &req, opportunity_enabled).await? {
        return Err(Failure("answer_reuse_context_changed"));
    }
    let stamp = Stamp::load_in(&mut tx, &req).await?;
    proof
        .claim_for(
            &mut tx,
            &format!("/api/v1/application-answers/drafts/{id}/approve-reuse"),
        )
        .await?;
    let value = json!({"approved":true,"profile_id":owner,"profile_version":profile.version,"draft_hash":draft_digest(&draft)?,"evidence_hash":stamp.evidence(),"job_hash":stamp.job(),"scope":input.scope,"intent":intent});
    let saved:Value=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=clock_timestamp() RETURNING value").bind(format!("answer:{id}")).bind(&value).fetch_one(&mut *tx).await.map_err(db)?;
    if saved != value {
        return Err(Failure("invalid_answer_reuse_record"));
    }
    let result = json!({"draft_id":id,"scope":input.scope,"approved":true,"intent":intent,"profile_version":profile.version});
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub async fn reuse_in(
    tx: &mut Transaction<'_, Postgres>,
    profile: &Value,
    request: &Generate,
    category: &str,
    limits: Limits,
    opportunity_enabled: bool,
) -> Result<Option<Value>> {
    let Some(intent) = semantic_intent(&request.question, category, profile)? else {
        return Ok(None);
    };
    let id = profile["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_profile_record"))?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('draft',to_jsonb(d),'binding',p.value) FROM application_answer_drafts d JOIN owner_preferences p ON p.key='answer:'||d.id::text WHERE d.candidate_profile_id=$1 AND d.candidate_profile_version=$2 AND d.review_status='reviewed' AND d.writing_style=$3 ORDER BY d.updated_at DESC,d.id LIMIT 100").bind(id).bind(profile["version"].as_i64().ok_or(Failure("invalid_profile_record"))? as i32).bind(&request.writing_style).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.is_empty() {
        return Ok(None);
    }
    let stamp = Stamp::load_in(tx, request).await?;
    for row in rows {
        let draft = &row["draft"];
        let binding = &row["binding"];
        crate::answer_store::record(draft.clone(), stamp.profile_version())?;
        if binding["approved"] != true
            || binding["intent"] != intent
            || binding["profile_id"] != profile["id"]
            || binding["profile_version"] != profile["version"]
            || binding["draft_hash"] != draft_digest(draft)?
            || binding["evidence_hash"] != stamp.evidence()
            || !["same_job", "general_profile"]
                .iter()
                .any(|s| binding["scope"] == *s)
        {
            continue;
        }
        if binding["scope"] == "same_job"
            && (draft["job_id"] != json!(request.job_id)
                || binding["job_hash"] != json!(stamp.job()))
        {
            continue;
        }
        if !current_references(tx, draft, request, opportunity_enabled).await? {
            continue;
        }
        let mut result = answer_contract::result(category, &request.writing_style);
        result["answer"] = json!(grounding::trim(
            draft["answer"]
                .as_str()
                .ok_or(Failure("invalid_answer_draft_record"))?
        ));
        result = limits.enforce(result);
        if result["answer"].is_null() {
            continue;
        }
        result["status"] = json!("draft_ready");
        result["source"] = json!("approved_answer");
        result["confidence"] = json!(0.95);
        result["evidence_references"] = draft["evidence_references"].clone();
        result["draft_id"] = draft["id"].clone();
        result["reused_draft_id"] = draft["id"].clone();
        result["warnings"] = json!([
            "Reused an explicitly approved answer with the same supported intent and current evidence; review for this form"
        ]);
        return Ok(Some(result));
    }
    Ok(None)
}
pub async fn revoke(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = begin(connection, false).await?;
    let profile = profile_store::get(&mut tx).await?;
    let owner = profile.value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_profile_record"))?;
    let row:Option<Uuid>=sqlx::query_scalar("SELECT id FROM application_answer_drafts WHERE id=$1 AND candidate_profile_id=$2 FOR UPDATE").bind(id).bind(owner).fetch_optional(&mut *tx).await.map_err(db)?;
    if row.is_none() {
        return Err(Failure("answer_draft_not_found"));
    }
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{approved}','false'::jsonb),updated_at=clock_timestamp() WHERE key=$1").bind(format!("answer:{id}")).execute(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)?;
    Ok(json!({"draft_id":id,"approved":false}))
}
pub async fn approvals(
    connection: &mut PgConnection,
    enabled: bool,
    owner_key: bool,
) -> Result<Value> {
    let mut tx = begin(connection, true).await?;
    let profile = profile_store::get(&mut tx).await?;
    let owner = profile.value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_profile_record"))?;
    let mut approvals = serde_json::Map::new();
    if enabled {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',d.id,'approved',p.value->'approved','scope',p.value->'scope') FROM application_answer_drafts d JOIN owner_preferences p ON p.key='answer:'||d.id::text WHERE d.candidate_profile_id=$1 ORDER BY d.updated_at DESC LIMIT 100").bind(owner).fetch_all(&mut *tx).await.map_err(db)?;
        for row in rows {
            let key = row["id"]
                .as_str()
                .ok_or(Failure("invalid_answer_reuse_record"))?;
            approvals.insert(
                key.into(),
                json!({"approved":row["approved"].as_bool().unwrap_or(false),"scope":row["scope"]}),
            );
        }
    }
    tx.commit().await.map_err(db)?;
    Ok(json!({"enabled":enabled,"owner_approval_available":owner_key,"approvals":approvals}))
}
/// Historical reviewed excerpts are read-only evidence; current reuse is checked separately.
pub async fn opportunity_evidence(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = begin(connection, true).await?;
    let profile = profile_store::get(&mut tx).await?;
    let owner = profile.value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("invalid_profile_record"))?;
    let draft:Value=sqlx::query_scalar("SELECT to_jsonb(d) FROM application_answer_drafts d WHERE id=$1 AND candidate_profile_id=$2").bind(id).bind(owner).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("answer_draft_not_found"))?;
    crate::answer_store::record(draft.clone(), profile.version)?;
    let mut result = vec![];
    for reference in references(&draft)? {
        let kind = match reference.source_type.as_str() {
            "opportunity_job" => "job",
            "opportunity_company" => "company",
            _ => continue,
        };
        let digest = reference.source_id.split(':').next().unwrap_or("");
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            continue;
        }
        let saved: Option<Value> =
            sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(format!("opp:{}", &digest[..40]))
                .fetch_optional(&mut *tx)
                .await
                .map_err(db)?;
        let Some(saved) = saved else {
            continue;
        };
        if saved["digest"] != digest || saved["job_id"] != draft["job_id"] {
            continue;
        }
        let mut material = saved.clone();
        let Some(map) = material.as_object_mut() else {
            continue;
        };
        map.remove("digest");
        map.remove("job_id");
        if crate::python_json::digest(&material) != digest {
            continue;
        }
        let source = if kind == "company" {
            saved
                .get("company_source_url")
                .unwrap_or(&saved["source_url"])
        } else {
            &saved["source_url"]
        };
        result.push(json!({"reference":reference,"source_url":source,"reviewed_at":saved["reviewed_at"],"excerpt":saved[format!("{kind}_text")]}));
    }
    tx.commit().await.map_err(db)?;
    Ok(json!({"evidence":result}))
}
