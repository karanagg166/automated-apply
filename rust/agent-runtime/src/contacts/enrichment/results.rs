//! Immutable provider findings precede identity ingestion. Lost responses never authorize another POST.
use super::*;
use sha2::{Digest, Sha256};
fn hash(value: &Value) -> String {
    format!("{:x}", Sha256::digest(value.to_string().as_bytes()))
}
fn changed() -> Failure {
    Failure("contact_provider_result_context_changed")
}
fn ack() -> Failure {
    Failure("contact_provider_result_write_ack_failed")
}
fn result_key(claim: &lookups::Claim) -> String {
    format!("cl_result:{}", claim.id())
}
fn intent_key(run: &runs::Run, claim: &lookups::Claim) -> String {
    format!("{}{}", lookups::prefix(run.id()), claim.id())
}
async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("contact_provider_result_commit_outcome_unknown"))
}
async fn read(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=524288 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(key).fetch_optional(&mut **tx).await.map_err(db)?;
    value.map(|v| v.ok_or_else(invalid)).transpose()
}
async fn put_new(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(ack());
    }
    Ok(())
}
async fn replace(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    before: &Value,
    after: &Value,
) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$3,updated_at=clock_timestamp() WHERE key=$1 AND value::jsonb=$2::jsonb RETURNING value").bind(key).bind(before).bind(after).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(after) {
        return Err(ack());
    }
    Ok(())
}
fn public(value: &Value) -> Value {
    json!({"state":value["outcome"]["state"],"outcome_unknown":value["outcome"]["outcome_unknown"],"provider_run_id":value["outcome"]["provider_run_id"],"error_code":value["outcome"]["error_code"],"observations_retained":value["outcome"]["observations"].as_array().map(Vec::len),"record_basis":"retained_provider_finding","identity_ingested":false,"post_admissions":1,"outbound_messages_sent":0})
}
pub async fn record(
    c: &mut PgConnection,
    run: &runs::Run,
    claim: &lookups::Claim,
    outcome: &providers::Outcome,
) -> Result<Value> {
    let binding = outcome.binding()?;
    let request = person::normalize(person::Kind::Request, claim.request().clone())?;
    if claim.run_id() != run.id()
        || binding.reservation != claim.id()
        || binding.provider != claim.provider()
        || binding.request_hash != hash(&request)
    {
        return Err(changed());
    }
    let snapshot = outcome.snapshot();
    if snapshot.to_string().len() > 400000 || outcome.observations.len() > 25 {
        return Err(invalid());
    }
    if !matches!(
        outcome.state,
        "completed"
            | "not_found"
            | "rate_limited"
            | "budget_exhausted"
            | "failed"
            | "unsupported_operation"
            | "billing_uncertain"
            | "authorization_required"
            | "queued"
            | "running"
    ) {
        return Err(invalid());
    }
    let operation = if request["person_id"].is_null() {
        "search_people"
    } else {
        "enrich_person"
    };
    let mut observations = Vec::new();
    for observation in &outcome.observations {
        let normalized = person::normalize(person::Kind::Observation, observation.clone())?;
        if normalized != *observation
            || normalized["source"] != claim.provider()
            || normalized["human_confirmed"] != false
            || normalized["email_status"] == "verified"
        {
            return Err(changed());
        }
        observations.push(normalized);
    }
    if outcome.state != "completed" && !observations.is_empty() {
        return Err(changed());
    }
    let fingerprint = hash(&snapshot);
    let key = result_key(claim);
    let mut tx = begin(c).await?;
    if let Some(existing) = read(&mut tx, &key).await? {
        if existing["schema_version"] != 1
            || existing["run_id"] != run.id().to_string()
            || existing["company_id"] != run.company().to_string()
            || existing["reservation_id"] != claim.id()
            || existing["provider"] != claim.provider()
            || existing["request_sha256"] != binding.request_hash
            || existing["invocation"] != binding.invocation.to_string()
            || existing["result_sha256"] != fingerprint
            || existing["outcome"] != snapshot
        {
            return Err(Failure("contact_provider_result_conflict"));
        }
        let result = public(&existing);
        commit(tx).await?;
        return Ok(result);
    }
    let post = read(&mut tx, &format!("cl_post:{}", claim.id()))
        .await?
        .ok_or_else(changed)?;
    let before = read(&mut tx, &intent_key(run, claim))
        .await?
        .ok_or_else(changed)?;
    if post["schema_version"] != 1
        || post["reservation_id"] != claim.id()
        || post["run_id"] != run.id().to_string()
        || post["invocation"] != binding.invocation.to_string()
        || post["provider"] != claim.provider()
        || post["request_sha256"] != binding.request_hash
        || post["post_admissions"] != 1
        || post["admission_only"] != true
        || before["dispatch_invocation"] != post["invocation"]
        || before["state"] != "dispatch_unknown"
        || before["post_admissions"] != 1
        || before["request"] != *claim.request()
    {
        return Err(changed());
    }
    let saved_run:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=300000 THEN to_jsonb(r) ELSE NULL END FROM contact_enrichment_runs r WHERE id=$1 FOR UPDATE").bind(run.id()).fetch_optional(&mut *tx).await.map_err(db)?.ok_or_else(changed)?;
    let mut saved_run = saved_run.ok_or_else(invalid)?;
    if saved_run["company_id"] != run.company().to_string()
        || saved_run["request_hash"] != runs::request_hash(run.company(), run.input())?
    {
        return Err(changed());
    }
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let record = json!({"schema_version":1,"run_id":run.id(),"company_id":run.company(),"reservation_id":claim.id(),"provider":claim.provider(),"invocation":binding.invocation,"request_sha256":binding.request_hash,"result_sha256":fingerprint,"outcome":snapshot,"recorded_at":now,"post_admissions":1});
    put_new(&mut tx, &key, &record).await?;
    let lookup: Uuid = before["lookup_id"]
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(changed)?;
    let original_lookup: Value = sqlx::query_scalar(
        "SELECT to_jsonb(l) FROM contact_provider_lookups l WHERE id=$1 FOR UPDATE",
    )
    .bind(lookup)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?
    .ok_or_else(changed)?;
    if original_lookup["reservation_id"] != claim.id()
        || original_lookup["state"] != "running"
        || original_lookup["provider"] != claim.provider()
        || original_lookup["company_id"] != run.company().to_string()
        || original_lookup["identity_key"] != before["identity_key"]
    {
        return Err(changed());
    }
    let mut expected_lookup = original_lookup.clone();
    expected_lookup["state"] = json!(outcome.state);
    let updated:Option<Value>=sqlx::query_scalar("UPDATE contact_provider_lookups l SET state=$3 WHERE id=$1 AND to_jsonb(l)=$2::jsonb RETURNING to_jsonb(l)").bind(lookup).bind(&original_lookup).bind(outcome.state).fetch_optional(&mut *tx).await.map_err(db)?;
    if updated.as_ref() != Some(&expected_lookup) {
        return Err(ack());
    }
    if let Some(reservation) = claim.reservation() {
        let actual = outcome
            .credits_used
            .map(i64::try_from)
            .transpose()
            .map_err(|_| invalid())?;
        budget::finish_in(
            &mut tx,
            reservation,
            outcome.state,
            actual,
            outcome.provider_run_id.as_deref(),
        )
        .await?;
    }
    if outcome.state == "rate_limited" {
        budget::cooldown_in(
            &mut tx,
            claim.provider(),
            outcome.retry_after_seconds.unwrap_or(60),
        )
        .await?;
    }
    let mut after = before.clone();
    after["state"] = json!("observed");
    after["result_state"] = json!(outcome.state);
    after["result_sha256"] = json!(fingerprint);
    after["outcome_unknown"] = json!(outcome.outcome_unknown);
    after["usable_profile_result"] = json!(false);
    after["missing_business_email"] = json!(false);
    after["recorded_at"] = now;
    replace(&mut tx, &intent_key(run, claim), &before, &after).await?;
    let mut usage = saved_run["usage"]
        .as_array()
        .filter(|u| u.len() < 100)
        .ok_or_else(invalid)?
        .clone();
    if usage.iter().any(|u| u["reservation_id"] == claim.id()) {
        return Err(Failure("contact_provider_result_conflict"));
    }
    usage.push(json!({"provider":claim.provider(),"operation":operation,"state":outcome.state,"reserved_estimate":claim.reservation().map(budget::Reservation::amount).unwrap_or(0),"confirmed_provider_credits":outcome.credits_used,"reservation_id":claim.id(),"provider_run_id":outcome.provider_run_id}));
    let before_run = saved_run.clone();
    saved_run["usage"] = json!(usage);
    let saved:Option<Value>=sqlx::query_scalar("UPDATE contact_enrichment_runs r SET usage=$3 WHERE id=$1 AND to_jsonb(r)=$2::jsonb RETURNING to_jsonb(r)").bind(run.id()).bind(&before_run).bind(&saved_run["usage"]).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&saved_run) {
        return Err(ack());
    }
    commit(tx).await?;
    Ok(public(&record))
}

pub async fn ingest(
    c: &mut PgConnection,
    run: &runs::Run,
    claim: &lookups::Claim,
    settings: &Settings,
    contacts_settings: &super::super::Settings,
) -> Result<Value> {
    if claim.run_id() != run.id() {
        return Err(changed());
    }
    let mut tx = begin(c).await?;
    let receipt_key = format!("cl_ingest:{}", claim.id());
    if let Some(saved) = read(&mut tx, &receipt_key).await? {
        if saved["schema_version"] != 1
            || saved["run_id"] != run.id().to_string()
            || saved["reservation_id"] != claim.id()
            || saved["request_sha256"]
                != hash(&person::normalize(
                    person::Kind::Request,
                    claim.request().clone(),
                )?)
        {
            return Err(changed());
        }
        let result = saved["result"].clone();
        commit(tx).await?;
        return Ok(result);
    }
    let result = read(&mut tx, &result_key(claim))
        .await?
        .ok_or_else(changed)?;
    let intent_key = intent_key(run, claim);
    let before = read(&mut tx, &intent_key).await?.ok_or_else(changed)?;
    if result["schema_version"] != 1
        || result["run_id"] != run.id().to_string()
        || result["reservation_id"] != claim.id()
        || result["provider"] != claim.provider()
        || result["result_sha256"] != hash(&result["outcome"])
        || before["result_sha256"] != result["result_sha256"]
        || before["state"] != "observed"
        || before["post_admissions"] != 1
    {
        return Err(changed());
    }
    let mut findings = Vec::new();
    let mut held = None;
    // A current run/context check is intentionally optional for retaining the remote result,
    // but mandatory for changing local professional identity facts.
    if let Err(error) = runs::guard_in(&mut tx, run, settings).await {
        if matches!(
            error.0,
            "contact_run_context_changed" | "contact_company_not_found"
        ) {
            held = Some("contact_result_context_requires_review");
        } else {
            return Err(error);
        }
    }
    if held.is_none() {
        if let Some(id) = claim.request()["person_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
        {
            let version:Option<String>=sqlx::query_scalar("SELECT xmin::text||':'||extract(epoch from updated_at)::text FROM contacts WHERE id=$1 AND company_id=$2 FOR UPDATE").bind(id).bind(run.company()).fetch_optional(&mut *tx).await.map_err(db)?;
            if version.as_deref() != Some(claim.target_version()) {
                held = Some("contact_result_target_changed_requires_review");
            }
        }
    }
    let observations = result["outcome"]["observations"]
        .as_array()
        .filter(|a| a.len() <= 25)
        .ok_or_else(invalid)?;
    let state = result["outcome"]["state"].as_str().ok_or_else(invalid)?;
    if held.is_none() && state == "completed" {
        for (index, observation) in observations.iter().enumerate() {
            let observation = person::normalize(person::Kind::Observation, observation.clone())?;
            if observation["source"] != claim.provider() || observation["human_confirmed"] != false
            {
                return Err(changed());
            }
            let profile_matches = claim.request()["person_id"].is_null()
                || observation["linkedin_url"]
                    .as_str()
                    .is_some_and(|p| Some(p) == claim.request()["linkedin_url"].as_str());
            if !profile_matches {
                held = Some("contact_provider_profile_result_requires_review");
                break;
            }
            let receipt = hash(
                &json!({"reservation":claim.id(),"result_sha256":result["result_sha256"],"observation":index}),
            );
            let finding = identity::reconcile_in(
                &mut tx,
                run.company(),
                observation,
                &receipt,
                contacts_settings,
            )
            .await?;
            findings.push(finding);
        }
    }
    // No fallback can be justified by a partial/held ingestion or suppressed/conflicting result.
    let usable = held.is_none()
        && state == "completed"
        && !findings.is_empty()
        && findings.iter().all(|f| {
            f["requires_review"] == false
                && f["conflicts"].as_array().is_some_and(Vec::is_empty)
                && !f["contact_id"].is_null()
        });
    let missing = usable && observations.iter().all(|o| !rules::truthy(&o["email"]));
    let finding = json!({"state":state,"findings":findings,"held_reason":held,"usable_profile_result":usable,"missing_business_email":missing,"outbound_messages_sent":0,"record_basis":"retained_identity_ingestion"});
    put_new(&mut tx,&receipt_key,&json!({"schema_version":1,"run_id":run.id(),"reservation_id":claim.id(),"request_sha256":hash(&person::normalize(person::Kind::Request,claim.request().clone())?),"result_sha256":result["result_sha256"],"result":finding})).await?;
    let mut after = before.clone();
    after["identity_ingestion"] = finding.clone();
    after["usable_profile_result"] = json!(usable);
    after["missing_business_email"] = json!(missing);
    replace(&mut tx, &intent_key, &before, &after).await?;
    commit(tx).await?;
    Ok(finding)
}
