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
