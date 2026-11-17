//! Local run/invocation admission. No remote action is authorized by starting a run.
use super::*;
use sha2::{Digest, Sha256};
fn hash(raw: &str) -> String {
    format!("{:x}", Sha256::digest(raw.as_bytes()))
}
fn ack() -> Failure {
    Failure("contact_run_write_ack_failed")
}
fn conflict() -> Failure {
    Failure("contact_run_context_changed")
}
fn key(id: Uuid) -> String {
    format!("contact_run:{}", id.simple())
}
/// Match actual Pydantic declaration order and compact UTF-8 model_dump_json.
pub fn request_hash(company: Uuid, input: &Value) -> Result<String> {
    let input = contract::normalize(input.clone())?;
    let mut fields = Vec::new();
    for field in [
        "target_roles",
        "max_people",
        "providers",
        "allow_paid",
        "allow_fallback",
        "include_candidates",
    ] {
        fields.push(format!(
            "{}:{}",
            serde_json::to_string(field).map_err(|_| invalid())?,
            serde_json::to_string(&input[field]).map_err(|_| invalid())?
        ));
    }
    Ok(hash(&format!("{company}{{{}}}", fields.join(","))))
}
fn settings_hash(settings: &Settings) -> String {
    hash(&json!({"max_people":settings.max_people,"providers":settings.providers.iter().map(|p|json!({"name":p.name,"enabled":p.enabled,"credentials_configured":p.credentials_configured,"monthly_limit":p.monthly_limit,"per_run_limit":p.per_run_limit,"lookup_cost":p.lookup_cost})).collect::<Vec<_>>()} ).to_string())
}
pub struct Run {
    id: Uuid,
    company: Uuid,
    token: Uuid,
    request_hash: String,
    input: Value,
    started_at: DateTime<Utc>,
    deadline: DateTime<Utc>,
}
impl Run {
    pub fn id(&self) -> Uuid {
        self.id
    }
    pub fn company(&self) -> Uuid {
        self.company
    }
    pub(super) fn deadline(&self) -> DateTime<Utc> {
        self.deadline
    }
    pub fn input(&self) -> &Value {
        &self.input
    }
}
pub struct Start {
    pub record: Value,
    pub invocation: Option<Run>,
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
async fn now(tx: &mut Transaction<'_, Postgres>) -> Result<(Value, DateTime<Utc>)> {
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let time = serde_json::from_value(at.clone()).map_err(|_| invalid())?;
    Ok((at, time))
}
async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("contact_run_commit_outcome_unknown"))
}
async fn company_in(tx: &mut Transaction<'_, Postgres>, company: Uuid) -> Result<Value> {
    sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name,'domain',domain) FROM companies WHERE id=$1 FOR SHARE").bind(company).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("contact_company_not_found"))
}
pub async fn start(
    c: &mut PgConnection,
    company: Uuid,
    input: Value,
    settings: &Settings,
) -> Result<Start> {
    let input = contract::normalize(input)?;
    let request_hash = request_hash(company, &input)?;
    let mut tx = begin(c).await?;
    let company_record = company_in(&mut tx, company).await?;
    let idempotency = input["idempotency_key"].as_str();
    if let Some(idempotency) = idempotency {
        let previous:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=300000 THEN to_jsonb(r) ELSE NULL END FROM contact_enrichment_runs r WHERE idempotency_key=$1 FOR UPDATE").bind(idempotency).fetch_optional(&mut *tx).await.map_err(db)?;
        if let Some(previous) = previous {
            let previous = previous.ok_or_else(invalid)?;
            if previous["request_hash"] != request_hash
                || previous["company_id"] != company.to_string()
            {
                return Err(Failure("contact_run_idempotency_conflict"));
            }
            let mut record = policy::saved_run(previous)?;
            record["invocation_resumed"] = json!(false);
            commit(tx).await?;
            return Ok(Start {
                record,
                invocation: None,
            });
        }
    }
    let id = Uuid::new_v4();
    let token = Uuid::new_v4();
    let (at, time) = now(&mut tx).await?;
    let expected = json!({"id":id,"company_id":company,"request_hash":request_hash,"target_roles":input["target_roles"],"provider_plan":input["providers"],"state":"running","contact_ids":[],"counts":{},"usage":[],"errors":[],"started_at":at,"completed_at":null,"idempotency_key":idempotency});
    let row:Option<Value>=sqlx::query_scalar("INSERT INTO contact_enrichment_runs(id,company_id,request_hash,target_roles,provider_plan,state,contact_ids,counts,usage,errors,started_at,completed_at,idempotency_key) VALUES($1,$2,$3,$4,$5,'running','[]','{}','[]','[]',$6,NULL,$7) ON CONFLICT DO NOTHING RETURNING to_jsonb(contact_enrichment_runs)").bind(id).bind(company).bind(&request_hash).bind(&input["target_roles"]).bind(&input["providers"]).bind(time).bind(idempotency).fetch_optional(&mut *tx).await.map_err(db)?;
    if row.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let deadline = time + chrono::Duration::seconds(180);
    let invocation = json!({"schema_version":1,"id":id,"company_id":company,"request_hash":request_hash,"input":input,"company_snapshot":company_record,"settings_hash":settings_hash(settings),"token_hash":hash(&token.to_string()),"started_at":at,"lease_until":deadline,"authority":"same_process_original_invocation_only"});
    let stored:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key(id)).bind(&invocation).fetch_optional(&mut *tx).await.map_err(db)?;
    if stored.as_ref() != Some(&invocation) {
        return Err(ack());
    }
    let mut record = policy::saved_run(expected)?;
    record["invocation_resumed"] = json!(false);
    commit(tx).await?;
    Ok(Start {
        record,
        invocation: Some(Run {
            id,
            company,
            token,
            request_hash,
            input,
            started_at: time,
            deadline,
        }),
    })
}
pub(super) async fn guard_in(
    tx: &mut Transaction<'_, Postgres>,
    run: &Run,
    settings: &Settings,
) -> Result<Value> {
    let record: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 AND jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=32768 FOR UPDATE")
            .bind(key(run.id))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or_else(conflict)?;
    let (_, time) = now(tx).await?;
    let deadline = crate::gmail_history::contract::timestamp(&record["lease_until"])
        .map(|t| t.with_timezone(&Utc))
        .ok_or_else(conflict)?;
    let started = crate::gmail_history::contract::timestamp(&record["started_at"])
        .map(|t| t.with_timezone(&Utc))
        .ok_or_else(conflict)?;
    if record["schema_version"] != 1
        || record["id"] != run.id.to_string()
        || record["company_id"] != run.company.to_string()
        || record["request_hash"] != run.request_hash
        || record["input"] != run.input
        || record["token_hash"] != hash(&run.token.to_string())
        || record["settings_hash"] != settings_hash(settings)
        || record["authority"] != "same_process_original_invocation_only"
        || deadline != run.deadline
        || started != run.started_at
        || time < started
        || time >= deadline
    {
        return Err(conflict());
    }
    let company = company_in(tx, run.company).await?;
    if company != record["company_snapshot"] {
        return Err(conflict());
    }
    let current: Option<Value> = sqlx::query_scalar(
        "SELECT jsonb_build_object('request_hash',request_hash,'company_id',company_id,'state',state,'target_roles',target_roles,'provider_plan',provider_plan,'idempotency_key',idempotency_key) FROM contact_enrichment_runs WHERE id=$1 FOR UPDATE",
    )
    .bind(run.id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if current
        != Some(
            json!({"request_hash":run.request_hash,"company_id":run.company,"state":"running","target_roles":run.input["target_roles"],"provider_plan":run.input["providers"],"idempotency_key":run.input["idempotency_key"]}),
        )
    {
        return Err(conflict());
    }
    Ok(company)
}
pub async fn check(c: &mut PgConnection, run: &Run, settings: &Settings) -> Result<Value> {
    let mut tx = begin(c).await?;
    let company = guard_in(&mut tx, run, settings).await?;
    commit(tx).await?;
    Ok(company)
}

/// Closing history grants no further work. Original token/input remain required after expiry.
pub async fn finish(
    c: &mut PgConnection,
    run: &Run,
    selected: &[Uuid],
    errors: &[&str],
    requested_state: &str,
) -> Result<Value> {
    if selected.len() > 25
        || errors.len() > 100
        || errors.iter().any(|s| {
            s.is_empty()
                || s.len() > 100
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
        })
        || !matches!(
            requested_state,
            "completed"
                | "not_configured"
                | "authorization_required"
                | "not_found"
                | "failed"
                | "rate_limited"
                | "budget_exhausted"
                | "billing_uncertain"
                | "queued"
                | "running"
                | "unsupported_operation"
        )
    {
        return Err(Failure("invalid_contact_run_completion"));
    }
    let mut tx = begin(c).await?;
    let finish_key = format!("cl_finish:{}", run.id.simple());
    if let Some(record)=sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key=$1 AND octet_length(value::text)<=524288 FOR UPDATE").bind(&finish_key).fetch_optional(&mut *tx).await.map_err(db)?{
        if record["schema_version"]!=1||record["run_id"]!=run.id.to_string()||record["request_hash"]!=run.request_hash||record["token_hash"]!=hash(&run.token.to_string()){return Err(conflict());}let value=record["result"].clone();commit(tx).await?;return Ok(value);
    }
    let journal:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 AND octet_length(value::text)<=32768 FOR UPDATE").bind(key(run.id)).fetch_optional(&mut *tx).await.map_err(db)?.ok_or_else(conflict)?;
    if journal["id"] != run.id.to_string()
        || journal["company_id"] != run.company.to_string()
        || journal["request_hash"] != run.request_hash
        || journal["input"] != run.input
        || journal["token_hash"] != hash(&run.token.to_string())
    {
        return Err(conflict());
    }
    let before:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=300000 THEN to_jsonb(r) ELSE NULL END FROM contact_enrichment_runs r WHERE id=$1 FOR UPDATE").bind(run.id).fetch_optional(&mut *tx).await.map_err(db)?.ok_or_else(conflict)?;
    let before = before.ok_or_else(invalid)?;
    if before["state"] != "running"
        || before["company_id"] != run.company.to_string()
        || before["request_hash"] != run.request_hash
    {
        return Err(conflict());
    }
    let intents:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=32768 THEN value ELSE NULL END FROM owner_preferences WHERE starts_with(key,$1) ORDER BY key LIMIT 101").bind(lookups::prefix(run.id)).fetch_all(&mut *tx).await.map_err(db)?;
    if intents.len() > 100 {
        return Err(Failure("contact_lookup_inventory_requires_review"));
    }
    let intents = intents
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    let unknown = intents
        .iter()
        .any(|i| i["state"] == "dispatch_unknown" || i["outcome_unknown"] == true);
    let prepared = intents.iter().any(|i| i["state"] == "prepared");
    let state = if unknown {
        "billing_uncertain"
    } else if prepared && requested_state == "completed" {
        "failed"
    } else {
        requested_state
    };
    let (_, time) = now(&mut tx).await?;
    let (company, domain): (Option<String>, Option<String>) =
        sqlx::query_as("SELECT name,domain FROM companies WHERE id=$1 FOR SHARE")
            .bind(run.company)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
            .unwrap_or((None, None));
    let mut ids = selected.to_vec();
    ids.sort();
    ids.dedup();
    let maximum = run.input["max_people"].as_u64().ok_or_else(invalid)? as usize;
    let contacts:Vec<Value>=sqlx::query_scalar(sqlx::AssertSqlSafe(format!("SELECT {CONTACT} FROM contacts c WHERE c.id=ANY($1) AND c.company_id=$3 ORDER BY c.id FOR UPDATE"))).bind(&ids).bind(json!({})).bind(run.company).fetch_all(&mut *tx).await.map_err(db)?;
    let mut retained = Vec::new();
    let mut research = Vec::new();
    let mut errors = errors
        .iter()
        .map(|s| s.to_string())
        .collect::<BTreeSet<_>>();
    if contacts.len() != ids.len() || company.is_none() {
        errors.insert("contact_completion_inventory_changed_requires_review".into());
    }
    for contact in contacts.iter().take(maximum) {
        retained.push(contact["id"].clone());
        if run.input["include_candidates"] == true
            && !rules::truthy(&contact["email"])
            && contact["do_not_contact"] == false
            && !rules::truthy(&contact["metadata_"]["identity_review_required"])
        {
            if let Some(domain) = domain.as_deref() {
                let name = contact["full_name"].as_str().ok_or_else(invalid)?;
                let (first, last) = name.split_once(' ').unwrap_or((name, ""));
                let candidates = candidates::generate(first, last, domain, None)?;
                research.push(json!({"contact_id":contact["id"],"candidates":candidates.into_iter().take(6).collect::<Vec<_>>()}));
            }
        }
    }
    if unknown {
        errors.insert("contact_admitted_provider_outcome_requires_review".into());
    }
    let mut after = before.clone();
    after["state"] = json!(state);
    after["contact_ids"] = json!(retained);
    after["counts"] =
        json!({"contacts":retained.len(),"candidate_research":research,"outbound_messages_sent":0});
    after["errors"] = json!(errors.into_iter().take(50).collect::<Vec<_>>());
    after["completed_at"] = sqlx::query_scalar::<_, Value>("SELECT to_jsonb($1::timestamptz)")
        .bind(time)
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let updated:Option<Value>=sqlx::query_scalar("UPDATE contact_enrichment_runs r SET state=$3::jsonb->>'state',contact_ids=$3::jsonb->'contact_ids',counts=$3::jsonb->'counts',errors=$3::jsonb->'errors',completed_at=($3::jsonb->>'completed_at')::timestamptz WHERE id=$1 AND to_jsonb(r)=$2::jsonb RETURNING to_jsonb(r)").bind(run.id).bind(&before).bind(&after).fetch_optional(&mut *tx).await.map_err(db)?;
    if updated.as_ref() != Some(&after) {
        return Err(ack());
    }
    let result = policy::saved_run(after)?;
    let expected = json!({"schema_version":1,"run_id":run.id,"request_hash":run.request_hash,"token_hash":hash(&run.token.to_string()),"result":result});
    let actual:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(finish_key).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if actual.as_ref() != Some(&expected) {
        return Err(ack());
    }
    commit(tx).await?;
    Ok(result)
}
