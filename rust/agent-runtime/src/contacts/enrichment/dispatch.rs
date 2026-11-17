//! Commit one POST admission before transport. A lost response never yields a second grant.
use super::*;
use sha2::{Digest, Sha256};
pub struct Grant {
    provider: String,
    key_hash: String,
    request: Value,
    operation: capabilities::Operation,
    deadline: DateTime<Utc>,
    invocation: Uuid,
    reservation: String,
}
impl Grant {
    pub(super) fn provider(&self) -> &str {
        &self.provider
    }
    pub(super) fn key_hash(&self) -> &str {
        &self.key_hash
    }
    pub(super) fn request(&self) -> &Value {
        &self.request
    }
    pub(super) fn operation(&self) -> capabilities::Operation {
        self.operation
    }
    pub(super) fn deadline(&self) -> DateTime<Utc> {
        self.deadline
    }
    pub fn invocation(&self) -> Uuid {
        self.invocation
    }
    pub fn reservation(&self) -> &str {
        &self.reservation
    }
}
fn changed() -> Failure {
    Failure("contact_lookup_dispatch_context_changed")
}
fn ack() -> Failure {
    Failure("contact_lookup_write_ack_failed")
}
pub async fn authorize(
    c: &mut PgConnection,
    run: &runs::Run,
    claim: &lookups::Claim,
    proof: providers::LiveProof,
    client: &providers::Client,
    settings: &Settings,
    contacts_settings: &super::super::Settings,
) -> Result<Grant> {
    if claim.run_id() != run.id() || claim.provider() != client.provider() {
        return Err(changed());
    }
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    runs::guard_in(&mut tx, run, settings).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let key = format!("{}{}", lookups::prefix(run.id()), claim.id());
    let before:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 AND jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=32768 FOR UPDATE").bind(&key).fetch_optional(&mut *tx).await.map_err(db)?.ok_or_else(changed)?;
    if before["schema_version"] != 1
        || before["run_id"] != run.id().to_string()
        || before["provider"] != claim.provider()
        || before["reservation_id"] != claim.id()
        || before["state"] != "prepared"
        || before["post_admissions"] != 0
        || before["dispatch_authorized"] != false
        || before["request"] != *claim.request()
        || before["target_version"] != claim.target_version()
    {
        return Err(changed());
    }
    let operation = match before["operation"].as_str() {
        Some("search_people") => capabilities::Operation::Search,
        Some("enrich_person") => capabilities::Operation::Enrich,
        _ => return Err(changed()),
    };
    let cost = before["estimated_cost"]
        .as_i64()
        .filter(|n| (0..=100).contains(n))
        .ok_or_else(changed)?;
    proof.check(client, operation, cost, now)?;
    if run.input()["allow_paid"] != true {
        return Err(changed());
    }
    let request = person::normalize(person::Kind::Request, claim.request().clone())?;
    if request["company_id"] != run.company().to_string() || request["allow_paid"] != true {
        return Err(changed());
    }
    let company = super::super::company(&mut tx, run.company()).await?;
    match operation {
        capabilities::Operation::Enrich => {
            let id = request["person_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(changed)?;
            let contact: Value = sqlx::query_scalar(sqlx::AssertSqlSafe(format!(
                "SELECT {CONTACT} FROM contacts c WHERE c.id=$1 AND c.company_id=$3 FOR UPDATE"
            )))
            .bind(id)
            .bind(json!({}))
            .bind(run.company())
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
            .ok_or_else(changed)?;
            rules::output(&contact, &company, None, contacts_settings, now)?;
            if contact["review_version"] != claim.target_version()
                || contact["full_name"] != request["full_name"]
                || contact["linkedin_url"].as_str().and_then(lookups::linkedin)
                    != request["linkedin_url"].as_str().map(str::to_owned)
                || !(policy::needs_lookup(&contact, contacts_settings.cache_days, now)
                    || before["fallback"] == true && policy::fallback_target(&contact))
                || !policy::role_matches(
                    contact["role_title"].as_str(),
                    run.input()["target_roles"].as_array().ok_or_else(changed)?,
                )
            {
                return Err(changed());
            }
            let reservation = claim.reservation().ok_or_else(changed)?;
            if reservation.id() != claim.id()
                || reservation.provider() != claim.provider()
                || reservation.amount() != cost
            {
                return Err(changed());
            }
            let reserved:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_budget_reservations WHERE id=$1 AND provider=$2 AND month=$3 AND reserved=$4::numeric AND state='reserved' AND provider_run_id IS NULL AND reported_actual IS NULL)").bind(claim.id()).bind(claim.provider()).bind(reservation.month()).bind(cost.to_string()).fetch_one(&mut *tx).await.map_err(db)?;
            let accounted:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider=$1 AND month=$2 AND reserved>=$3::numeric)").bind(claim.provider()).bind(reservation.month()).bind(cost.to_string()).fetch_one(&mut *tx).await.map_err(db)?;
            if !reserved || !accounted {
                return Err(changed());
            }
        }
        capabilities::Operation::Search => {
            if cost != 0 || claim.reservation().is_some() || claim.provider() != "apollo" {
                return Err(changed());
            }
            let local = super::preview(
                &mut tx,
                run.company(),
                run.input(),
                settings,
                contacts_settings,
                now,
            )
            .await?;
            if local["contact_inventory_truncated"] == true
                || local["people_inventory_truncated"] == true
                || !local["cached_contacts"]
                    .as_array()
                    .is_some_and(Vec::is_empty)
                || !local["discovered_people"]
                    .as_array()
                    .is_some_and(Vec::is_empty)
            {
                return Err(changed());
            }
        }
    }
    let lookup:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM contact_provider_lookups WHERE id=$1 AND company_id=$2 AND provider=$3 AND identity_key=$4 AND reservation_id=$5 AND state='running' AND expires_at>$6)").bind(before["lookup_id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(changed)?).bind(run.company()).bind(claim.provider()).bind(before["identity_key"].as_str()).bind(claim.id()).bind(now).fetch_one(&mut *tx).await.map_err(db)?;
    let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider=$1 AND cooldown_until>$2)").bind(claim.provider()).bind(now).fetch_one(&mut *tx).await.map_err(db)?;
    if !lookup || cooling {
        return Err(changed());
    }
    if before["fallback"] == true {
        let providers = run.input()["providers"].as_array().ok_or_else(changed)?;
        let index = providers
            .iter()
            .position(|p| p == claim.provider())
            .filter(|i| *i > 0)
            .ok_or_else(changed)?;
        let prior:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,$1) AND octet_length(value::text)<=32768 ORDER BY key LIMIT 101").bind(lookups::prefix(run.id())).fetch_all(&mut *tx).await.map_err(db)?;
        if prior.len() > 100
            || run.input()["allow_fallback"] != true
            || !prior.iter().any(|p| {
                p["provider"] == providers[index - 1]
                    && p["target_key"] == before["target_key"]
                    && p["state"] == "observed"
                    && p["result_state"] == "completed"
                    && p["usable_profile_result"] == true
                    && p["missing_business_email"] == true
            })
        {
            return Err(changed());
        }
    }
    let deadline = run.deadline().min(proof.deadline());
    let invocation = Uuid::new_v4();
    let finding = proof.finding();
    let finding_hash = format!("{:x}", Sha256::digest(finding.to_string().as_bytes()));
    let mut after = before.clone();
    after["state"] = json!("dispatch_unknown");
    after["post_admissions"] = json!(1);
    after["dispatch_authorized"] = json!(true);
    after["dispatch_invocation"] = json!(invocation);
    after["dispatch_admitted_at"] = json!(now);
    after["metadata_proof_sha256"] = json!(finding_hash);
    after["metadata_key_sha256"] = json!(proof.key_hash());
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$3,updated_at=clock_timestamp() WHERE key=$1 AND value::jsonb=$2::jsonb RETURNING value").bind(&key).bind(&before).bind(&after).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&after) {
        return Err(ack());
    }
    let post = json!({"schema_version":1,"reservation_id":claim.id(),"run_id":run.id(),"invocation":invocation,"provider":claim.provider(),"request_sha256":format!("{:x}",Sha256::digest(request.to_string().as_bytes())),"metadata_proof_sha256":finding_hash,"metadata_key_sha256":proof.key_hash(),"post_admissions":1,"admitted_at":now,"dispatch_deadline":deadline,"admission_only":true});
    let written:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(format!("cl_post:{}",claim.id())).bind(&post).fetch_optional(&mut *tx).await.map_err(db)?;
    if written.as_ref() != Some(&post) {
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("contact_lookup_dispatch_commit_unknown"))?;
    Ok(Grant {
        provider: claim.provider().into(),
        key_hash: proof.key_hash().into(),
        request,
        operation,
        deadline,
        invocation,
        reservation: claim.id().into(),
    })
}

#[cfg(test)]
pub(crate) fn fixture_grant(
    provider: &str,
    key: &str,
    operation: capabilities::Operation,
    request: Value,
) -> Grant {
    Grant {
        provider: provider.into(),
        key_hash: format!("{:x}", Sha256::digest(key.as_bytes())),
        request: person::normalize(person::Kind::Request, request)
            .expect("fictional provider request"),
        operation,
        deadline: Utc::now() + chrono::Duration::seconds(30),
        invocation: Uuid::new_v4(),
        reservation: "contact_fixture_no_database_dispatch_proof".into(),
    }
}
