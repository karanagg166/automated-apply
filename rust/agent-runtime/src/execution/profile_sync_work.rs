//! Version-pinned ordinary profile comparison and separately admitted supported saves.
//! No provider/browser IO; original chips and all uncertain save intents are retained.
use super::{
    automatic,
    contracts::{self, Kind},
    preflight, profile_sync as facts, profile_sync_policy, queue_control,
    storage::*,
};
use crate::{Failure, Result, private_resume, resources};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub const WORK: &str = "apply_profile_sync:naukri";
pub const OPERATIONS: &[&str] = &["inspect_profile_sync", "sync_profile"];
async fn scope_in(tx: &mut Transaction<'_, Postgres>, writing: bool) -> Result<Value> {
    let queue = queue_control::configuration(tx).await?;
    if queue["state"] != "RUNNING" || queue["policy"]["platforms"]["naukri"]["enabled"] != true {
        return Err(Failure("profile_sync_context_changed"));
    }
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if execution["mode"] == "OFF" {
        return Err(Failure("execution_mode_off"));
    }
    let preference = super::local_policy::preference_in(tx, "naukri").await?;
    if preference == "disabled" {
        return Err(Failure("platform_disabled"));
    }
    if writing && matches!(preference, "manual_only" | "draft_only") {
        return Err(Failure("platform_policy_requires_manual_review"));
    }
    Ok(queue)
}
struct Context {
    profile: Value,
    resume: Option<resources::ResumeOption>,
}
async fn context_in(tx: &mut Transaction<'_, Postgres>) -> Result<Context> {
    let profile = preflight::profile_in(tx, &json!({})).await?;
    let owner = profile["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM candidate_resources r WHERE candidate_profile_id=$1 AND resource_type='resume' ORDER BY id LIMIT 10001").bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let resources = rows
        .into_iter()
        .map(|v| serde_json::from_value::<resources::Resource>(v).map_err(|_| invalid()))
        .collect::<Result<Vec<_>>>()?;
    let resume = resources::select_resume(&resources, None)?.selected;
    Ok(Context { profile, resume })
}
async fn resume_in(
    tx: &mut Transaction<'_, Postgres>,
    context: &Context,
    resumes: &private_resume::Settings,
) -> Result<Value> {
    let resume = context
        .resume
        .as_ref()
        .ok_or(Failure("canonical_private_pdf_unavailable_or_invalid"))?;
    let owner = context.profile["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let row:Option<(Vec<u8>,String)>=sqlx::query_as("SELECT p.ciphertext,p.sha256 FROM candidate_resources r JOIN private_resumes p ON r.url='private-resume:'||p.id::text AND p.resource_id=r.id WHERE r.id=$1 AND r.candidate_profile_id=$2 AND r.user_confirmed AND r.source_type='private_upload' AND p.confirmed").bind(resume.resource_id).bind(owner).fetch_optional(&mut **tx).await.map_err(db)?;
    let raw = row
        .and_then(|(bytes, hash)| resumes.verified(&bytes, &hash).ok())
        .filter(|raw| !raw.is_empty() && raw.len() <= 2_000_000)
        .ok_or(Failure("canonical_private_pdf_unavailable_or_invalid"))?;
    Ok(
        json!({"sha256":format!("{:x}",Sha256::digest(&raw)),"byte_count":raw.len(),"resource_id":resume.resource_id,"resource_version":resume.resource_version}),
    )
}
async fn policy_in(tx: &mut Transaction<'_, Postgres>) -> Result<(Value, Value)> {
    let config = profile_sync_policy::configuration_in(tx).await?;
    let policy =
        contracts::normalize(Kind::SyncPolicy, config["policy"].clone()).map_err(|_| invalid())?;
    Ok((config, policy))
}
pub(crate) async fn work_in(
    tx: &mut Transaction<'_, Postgres>,
    binding: &Value,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let queue = match scope_in(tx, false).await {
        Ok(queue) => queue,
        Err(Failure(
            "profile_sync_context_changed" | "execution_mode_off" | "platform_disabled",
        )) => return Ok(None),
        Err(error) => return Err(error),
    };
    let (config, policy) = policy_in(tx).await?;
    if policy["enabled"] != true {
        return Ok(None);
    }
    let old = get(tx, WORK).await?.unwrap_or(json!({"revision":0}));
    if !old["lease_until"].is_null() && timestamp(&old["lease_until"])? > now {
        return Ok(None);
    }
    // One ordinary read may reconcile a lost Save after its lease expires; never repeat that Save.
    let uncertain = old["early_reconcile"] == true
        || old["status"] == "executing"
            && old["operation"] == "sync_profile"
            && old["sync_attempt"]["outcome"] == "UNKNOWN";
    if !uncertain && !old["next_at"].is_null() && timestamp(&old["next_at"])? > now {
        return Ok(None);
    }
    let context = match context_in(tx).await {
        Ok(context) => context,
        Err(Failure("verified_profile_context_changed")) => return Ok(None),
        Err(error) => return Err(error),
    };
    if policy["auto_profile_sync"] == true
        && policy["profile_version"] != context.profile["version"]
    {
        return Ok(None);
    }
    let account = match automatic::account(tx).await {
        Ok(account) => account,
        Err(Failure(
            "approved_naukri_account_binding_required" | "naukri_account_binding_context_changed",
        )) => return Ok(None),
        Err(error) => return Err(error),
    };
    if account["candidate_profile_id"] != context.profile["id"]
        || account["profile_binding_id"] != binding["profile_binding_id"]
    {
        return Ok(None);
    }
    let mut value = json!({"id":Uuid::new_v5(&Uuid::NAMESPACE_URL,WORK.as_bytes()),"revision":next(&old)?,"policy_revision":queue["revision"],"sync_policy_revision":config["revision"],"profile_version":context.profile["version"],"binding":binding,"status":"leased","operation":"inspect_profile_sync","url":super::submission::PROFILE_URL,"requisition":null,"lease_token":Uuid::new_v4(),"lease_until":stamp(now+chrono::Duration::seconds(180)),"candidate_profile_id":context.profile["id"],"account_binding_revision":account["revision"],"account_sha256":account["account_sha256"],"next_at":stamp(now+chrono::Duration::seconds(policy["interval_seconds"].as_i64().ok_or_else(invalid)?)),"sync_attempt":old["sync_attempt"],"last_record":old["last_record"]});
    if policy["verify_saved_resume"] == true {
        value["upload_preflight"] = resume_in(tx, &context, resumes).await?;
        value["verify_saved_resume"] = json!(true);
    }
    if let Some(prior) = old.get("previous_verified_attempt") {
        value["previous_verified_attempt"] = prior.clone();
    }
    put(tx, WORK, &value).await?;
    Ok(Some(value))
}
async fn validate_in(tx: &mut Transaction<'_, Postgres>, work: &Value) -> Result<(Context, Value)> {
    scope_in(tx, work["operation"] == "sync_profile").await?;
    preflight::check_account_in(tx, work).await?;
    let (config, policy) = policy_in(tx).await?;
    let context = context_in(tx).await?;
    if policy["enabled"] != true
        || context.profile["version"] != work["profile_version"]
        || policy["auto_profile_sync"] == true
            && policy["profile_version"] != context.profile["version"]
        || config["revision"] != work["sync_policy_revision"]
    {
        return Err(Failure("profile_sync_context_changed"));
    }
    Ok((context, policy))
}
async fn record_in(tx: &mut Transaction<'_, Postgres>, record: &Value) -> Result<()> {
    let id = record["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value").bind(format!("nau_sync:{id}")).bind(record).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack.as_ref() != Some(record) {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok(())
}
fn reference_equals(value: &Value, reference: &Value) -> bool {
    json!(facts::reference(value)) == *reference
}
pub fn validate_attempt(attempt: &Value, now: DateTime<Utc>) -> Result<()> {
    let hash = |v: &Value| {
        v.as_str().is_some_and(|s| {
            s.len() == 64
                && s.bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
    };
    if attempt["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .is_none()
        || attempt["document_id"].as_str().is_none_or(|s| {
            !(16..=100).contains(&s.len())
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
        })
        || !hash(&attempt["new_reference"])
        || !attempt["previous_reference"].is_null() && !hash(&attempt["previous_reference"])
        || timestamp(&attempt["at"]).ok().is_none_or(|at| at > now)
        || !matches!(
            attempt["outcome"].as_str(),
            Some("UNKNOWN" | "SYNC_UNCONFIRMED_NO_RETRY" | "SYNC_VERIFIED")
        )
        || !attempt["field"].is_null()
            && !matches!(attempt["field"].as_str(), Some("summary" | "skills"))
    {
        return Err(Failure("profile_sync_attempt_requires_review"));
    }
    Ok(())
}
pub(crate) async fn admit_in(
    tx: &mut Transaction<'_, Postgres>,
    mut work: Value,
    _now: DateTime<Utc>,
) -> Result<Value> {
    let (context, policy) = validate_in(tx, &work).await?;
    if work["operation"] == "sync_profile" {
        let field = work["sync_field"].as_str().unwrap_or("summary").to_owned();
        if policy["auto_profile_sync"] != true
            || !policy["approved_fields"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .any(|f| f == &field)
            || !work["sync_attempt"].is_null()
        {
            return Err(Failure(
                "profile_sync_write_scope_or_reconciliation_required",
            ));
        }
        let (previous, desired) = if field == "skills" {
            if !reference_equals(
                &context.profile["verified_skills"],
                &work["canonical_skills_reference"],
            ) {
                return Err(Failure("profile_sync_canonical_value_changed"));
            }
            if work["sync_phase"] == "prepare" {
                work["status"] = json!("executing");
                work["revision"] = json!(next(&work)?);
                return Ok(work);
            }
            if work["sync_phase"] != "save" {
                return Err(Failure("profile_skills_preparation_required"));
            }
            let final_skills = facts::prepared(
                &work["skills_before"],
                &work["skills_additions"],
                &work["prepared_skills"],
            )?;
            let desired = json!(facts::reference(&facts::comparison_value(
                "skills",
                &json!(final_skills)
            )));
            if desired != work["new_skills_reference"] {
                return Err(Failure("profile_skills_prepared_value_changed"));
            }
            (work["previous_skills_reference"].clone(), desired)
        } else {
            if field != "summary"
                || context.profile["summary"]
                    .as_str()
                    .is_none_or(str::is_empty)
                || !reference_equals(&context.profile["summary"], &work["new_summary_reference"])
            {
                return Err(Failure("profile_sync_canonical_value_changed"));
            }
            work["approved_summary"] = context.profile["summary"].clone();
            (
                work["previous_summary_reference"].clone(),
                work["new_summary_reference"].clone(),
            )
        };
        let now = super::storage::now(tx).await?;
        let mut attempt = json!({"id":Uuid::new_v4(),"at":stamp(now),"document_id":work["document_id"],"previous_reference":previous,"new_reference":desired,"outcome":"UNKNOWN"});
        if field == "skills" {
            attempt["field"] = json!("skills");
        }
        validate_attempt(&attempt, now)?;
        work["sync_attempt"] = attempt.clone();
        work["permit_expires_at"] = json!(stamp(now + chrono::Duration::seconds(2)));
        let id = Uuid::new_v4();
        record_in(tx,&json!({"id":id,"profile_version":context.profile["version"],"sync_policy_revision":work["sync_policy_revision"],"observed_at":stamp(now),"decisions":[],"outcome":"SYNC_ADMITTED_OUTCOME_UNKNOWN","attempt":attempt})).await?;
        work["last_record"] = json!(id);
    }
    work["status"] = json!("executing");
    work["revision"] = json!(next(&work)?);
    Ok(work)
}

pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    report: &Value,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<bool> {
    let (context, policy) = validate_in(tx, work).await?;
    if matches!(report["kind"].as_str(), Some("needs_input" | "failed")) {
        let writing = work["operation"] == "sync_profile";
        work["status"] = json!("idle");
        work["last_error"] = report
            .get("reason")
            .filter(|v| v.as_str().is_some_and(|s| !s.is_empty()))
            .cloned()
            .unwrap_or(json!("profile_sync_observation_failed"));
        work.as_object_mut()
            .ok_or_else(invalid)?
            .remove("approved_summary");
        work.as_object_mut()
            .ok_or_else(invalid)?
            .remove("permit_expires_at");
        if !work["sync_attempt"].is_null() {
            let id = Uuid::new_v4();
            record_in(tx,&json!({"id":id,"profile_version":context.profile["version"],"sync_policy_revision":work["sync_policy_revision"],"observed_at":stamp(now),"decisions":[],"outcome":"SYNC_UNCONFIRMED_NO_RETRY","attempt":work["sync_attempt"],"failure_code":work["last_error"]})).await?;
            work["last_record"] = json!(id);
            work["early_reconcile"] = json!(writing);
        }
        return Ok(false);
    }
    let observation = &report["execution"];
    if report["kind"] != "execution_observation"
        || !observation.is_object()
        || observation["account_sha256"] != work["account_sha256"]
        || report["observed_url"] != work["url"]
    {
        return Err(Failure("profile_sync_account_or_document_changed"));
    }
    if work["operation"] == "sync_profile" {
        if work["sync_field"] == "skills" && work["sync_phase"] == "prepare" {
            if observation["state"] != "PROFILE_SKILLS_PREPARED"
                || observation["document_id"] != work["document_id"]
                || observation["profile_fields"]
                    .as_object()
                    .is_none_or(|o| o.len() != 1 || !o.contains_key("skills"))
            {
                return Err(Failure("profile_skills_prepared_observation_required"));
            }
            let final_skills = facts::prepared(
                &work["skills_before"],
                &work["skills_additions"],
                &observation["profile_fields"]["skills"],
            )?;
            work["prepared_skills"] = json!(final_skills);
            work["new_skills_reference"] = json!(facts::reference(&facts::comparison_value(
                "skills",
                &work["prepared_skills"]
            )));
            work["sync_phase"] = json!("save");
            work["status"] = json!("leased");
            return Ok(true);
        }
        if observation["state"] != "PROFILE_SAVE_ATTEMPTED" {
            return Err(Failure("profile_sync_save_observation_required"));
        }
        work.as_object_mut()
            .ok_or_else(invalid)?
            .remove("approved_summary");
        work.as_object_mut()
            .ok_or_else(invalid)?
            .remove("permit_expires_at");
        work["operation"] = json!("inspect_profile_sync");
        work["status"] = json!("leased");
        work["verifying_save"] = json!(true);
        return Ok(true);
    }
    if observation["state"] != "PROFILE_OBSERVED" {
        return Err(Failure("profile_sync_observation_required"));
    }
    let mut observed = observation["profile_fields"].clone();
    if !observed.is_object() {
        return Err(invalid());
    }
    let mut resume_verification = None;
    if policy["verify_saved_resume"] == true {
        let checked = resume_in(tx, &context, resumes).await?;
        if checked != work["upload_preflight"] {
            return Err(Failure("profile_sync_canonical_resume_changed"));
        }
        if observation["resume_sha256"] != checked["sha256"]
            || observation["resume_bytes"] != checked["byte_count"]
        {
            return Err(Failure("provider_saved_resume_differs_from_canonical_pdf"));
        }
        let resume = context.resume.as_ref().ok_or_else(invalid)?;
        observed["resume"] = json!(resume.resource_version);
        resume_verification = Some(
            json!({"state":"MATCHED_PDF_BYTES","byte_count":checked["byte_count"],"resource_version":resume.resource_version}),
        );
    }
    let canonical = facts::canonical(
        &context.profile,
        context.resume.as_ref().map(|r| r.resource_version.as_str()),
    );
    let approved: Vec<String> =
        serde_json::from_value(policy["approved_fields"].clone()).map_err(|_| invalid())?;
    let decisions = facts::compare(&canonical, &observed, &approved)?;
    let id = Uuid::new_v4();
    let mut record = json!({"id":id,"profile_version":context.profile["version"],"sync_policy_revision":work["sync_policy_revision"],"observed_at":stamp(now),"decisions":decisions,"evidence_sha256":observation["evidence_sha256"],"document_id":observation["document_id"],"outcome":"COMPARED","attempt":work["sync_attempt"]});
    if let Some(verification) = resume_verification {
        record["resume_verification"] = verification;
    }
    let summary = decisions
        .iter()
        .find(|d| d["field"] == "summary")
        .ok_or_else(invalid)?;
    if !work["sync_attempt"].is_null() {
        validate_attempt(&work["sync_attempt"], now)?;
        if work["sync_attempt"]["document_id"] == observation["document_id"] {
            return Err(Failure("independent_profile_reload_required"));
        }
        let matched = if work["sync_attempt"]["field"] == "skills" {
            reference_equals(
                &facts::comparison_value("skills", &observed["skills"]),
                &work["sync_attempt"]["new_reference"],
            )
        } else {
            summary["state"] == "MATCHED"
                && summary["new_reference"] == work["sync_attempt"]["new_reference"]
        };
        let outcome = if matched {
            "SYNC_VERIFIED"
        } else {
            "SYNC_UNCONFIRMED_NO_RETRY"
        };
        record["outcome"] = json!(outcome);
        work["sync_attempt"]["outcome"] = json!(outcome);
        // Only independently verified persistence ends the active intent. Its immutable
        // admission/verification records remain; an uncertain save can never be cleared.
        if matched {
            let mut verified = work["sync_attempt"].clone();
            verified["verification_record"] = json!(id);
            verified["verified_document_id"] = observation["document_id"].clone();
            work["previous_verified_attempt"] = verified;
            work["sync_attempt"] = Value::Null;
        }
    }
    work["last_record"] = json!(id);
    work["last_error"] = Value::Null;
    work["status"] = json!("idle");
    work["early_reconcile"] = json!(false);
    record_in(tx, &record).await?;
    super::profile_sync_notices::missing_in(tx, &decisions).await?;
    let writable = !matches!(
        super::local_policy::preference_in(tx, "naukri").await?,
        "manual_only" | "draft_only" | "disabled"
    );
    if writable
        && policy["auto_profile_sync"] == true
        && summary["may_update"] == true
        && work["sync_attempt"].is_null()
    {
        work["operation"] = json!("sync_profile");
        work["sync_field"] = json!("summary");
        work["status"] = json!("leased");
        work["document_id"] = observation["document_id"].clone();
        work["previous_summary_reference"] = summary["previous_reference"].clone();
        work["new_summary_reference"] = summary["new_reference"].clone();
        return Ok(true);
    }
    let skills = decisions
        .iter()
        .find(|d| d["field"] == "skills")
        .ok_or_else(invalid)?;
    if writable
        && policy["auto_profile_sync"] == true
        && skills["may_update"] == true
        && work["sync_attempt"].is_null()
    {
        let before = facts::skills(&observed["skills"], true)?;
        let additions = facts::additions(&context.profile["verified_skills"], &json!(before))?;
        work["operation"] = json!("sync_profile");
        work["sync_field"] = json!("skills");
        work["sync_phase"] = json!("prepare");
        work["status"] = json!("leased");
        work["document_id"] = observation["document_id"].clone();
        work["skills_before"] = json!(before);
        work["skills_additions"] = json!(additions);
        work["canonical_skills_reference"] =
            json!(facts::reference(&context.profile["verified_skills"]));
        work["previous_skills_reference"] = json!(facts::reference(&facts::comparison_value(
            "skills",
            &work["skills_before"]
        )));
        return Ok(true);
    }
    Ok(false)
}
/// Current-step transport only; all canonical contacts, past attempts and private PDF bytes stay local.
pub fn descriptor(work: &Value) -> Value {
    let mut value = super::submission::descriptor(work);
    value["approved_summary"] = work["approved_summary"].clone();
    value["verify_saved_resume"] = work
        .get("verify_saved_resume")
        .cloned()
        .unwrap_or(json!(false));
    value["previous_summary_reference"] = work["previous_summary_reference"].clone();
    if work["sync_field"] == "skills" {
        for key in [
            "sync_field",
            "sync_phase",
            "skills_before",
            "skills_additions",
            "prepared_skills",
            "previous_skills_reference",
            "new_skills_reference",
        ] {
            value[key] = work[key].clone();
        }
    }
    value
}

async fn checked_in(
    tx: &mut Transaction<'_, Postgres>,
    request: &super::admission::Request<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let work = get(tx, WORK)
        .await?
        .ok_or(Failure("queue_item_not_found"))?;
    let queue = scope_in(tx, false).await?;
    if request.identity != Uuid::new_v5(&Uuid::NAMESPACE_URL, WORK.as_bytes())
        || work["id"] != request.identity.to_string()
        || work["revision"] != request.revision
        || work["policy_revision"] != queue["revision"]
        || work["lease_token"] != request.token.to_string()
        || &work["binding"] != request.binding
        || !matches!(work["status"].as_str(), Some("leased" | "executing"))
        || work["lease_until"].is_null()
        || timestamp(&work["lease_until"])? <= now
    {
        return Err(Failure("queue_lease_lost"));
    }
    Ok(work)
}
/// Host-internal scheduling; the native broker authenticates the browser binding first.
pub async fn work(
    c: &mut sqlx::PgConnection,
    binding: &Value,
    resumes: &private_resume::Settings,
) -> Result<Option<Value>> {
    use sqlx::Connection;
    if !binding.is_object()
        || binding["profile_binding_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none()
    {
        return Err(Failure("invalid_execution_contract"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        work_in(&mut tx, binding, resumes, now).await
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
/// An editor preparation never carries a Save permit. A Save returns only after its intent commits.
pub async fn admit(
    c: &mut sqlx::PgConnection,
    request: super::admission::Request<'_>,
) -> Result<Value> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let work = checked_in(&mut tx, &request, now).await?;
        if work["status"] != "leased" {
            return Err(Failure("queue_action_already_admitted"));
        }
        let work = admit_in(&mut tx, work, now).await?;
        let now = super::storage::now(&mut tx).await?;
        checked_in(&mut tx, &request, now).await?;
        put(&mut tx, WORK, &work).await?;
        Ok(work)
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
/// Validate and retain one exact native observation; no profile action is dispatched here.
pub async fn observe(
    c: &mut sqlx::PgConnection,
    request: super::admission::Request<'_>,
    report: Value,
    resumes: &private_resume::Settings,
) -> Result<Value> {
    use sqlx::Connection;
    let report = crate::browser_profiles::native_contract::work_report(report)?;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut work = checked_in(&mut tx, &request, now).await?;
        if work["status"] != "executing" {
            return Err(Failure("queue_action_not_admitted"));
        }
        let continuing = receive_in(&mut tx, &mut work, &report, resumes, now).await?;
        work["revision"] = json!(next(&work)?);
        if !continuing {
            work["lease_token"] = Value::Null;
            work["lease_until"] = Value::Null;
        }
        put(&mut tx, WORK, &work).await?;
        Ok(work)
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
