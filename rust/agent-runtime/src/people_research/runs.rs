//! One original search admission. Reading/replaying a saved row never reconstructs a grant.
use super::settings::Settings;
use crate::{
    Failure, Result,
    contacts::enrichment::budget,
    research_contract::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("public_research_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_public_research_record")
}
fn ack() -> Failure {
    Failure("public_research_write_ack_failed")
}
pub(super) fn key(id: Uuid) -> String {
    format!("people_search:{}", id.simple())
}
pub(super) fn time(value: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str().ok_or_else(invalid)?)
        .map(|v| v.to_utc())
        .map_err(|_| invalid())
}
pub(super) async fn company_in(tx: &mut Transaction<'_, Postgres>, input: &Value) -> Result<Value> {
    let Some(domain) = input["company_domain"].as_str() else {
        return Ok(Value::Null);
    };
    let rows:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=1048576 THEN to_jsonb(c) ELSE NULL END FROM companies c WHERE domain=$1 ORDER BY id LIMIT 2").bind(domain).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(Failure("public_research_company_identity_ambiguous"));
    }
    rows.into_iter()
        .next()
        .unwrap_or(Some(Value::Null))
        .ok_or_else(invalid)
}
pub struct Claim {
    pub(super) id: Uuid,
    pub(super) journal: Value,
    pub(super) reservation: budget::Reservation,
    pub(super) grant: Option<Grant>,
}
impl Claim {
    pub fn id(&self) -> Uuid {
        self.id
    }
}
/// Internal single-use transport value; no Clone, Debug, deserialization or public constructor.
pub(super) struct Grant {
    pub(super) id: Uuid,
    pub(super) invocation: Uuid,
    pub(super) context: String,
    pub(super) body: Value,
    pub(super) deadline: DateTime<Utc>,
    pub(super) input: Value,
    pub(super) permission: Option<String>,
}
pub enum Admission {
    Retained(Value),
    Original(Box<Claim>),
}
pub fn output(journal: &Value, request: Uuid, now: DateTime<Utc>) -> Result<Value> {
    if journal["schema"] != 1
        || journal["request_id"] != json!(request)
        || journal["post_admissions"] != 1
        || !matches!(
            journal["state"].as_str(),
            Some("dispatch_admitted" | "finding_retained")
        )
    {
        return Err(invalid());
    }
    let expires = time(&journal["expires_at"])?;
    let started = time(&journal["started_at"])?;
    if expires <= started || expires > started + chrono::Duration::seconds(30) {
        return Err(invalid());
    }
    let company = journal["input"]["company_name"]
        .as_str()
        .filter(|s| s.chars().count() <= 200)
        .ok_or_else(invalid)?;
    if journal["state"] == "finding_retained" {
        let finding = super::findings::selected(journal, now)?;
        let mut value = json!({"request_id":request,"company_name":company,"status":if matches!(finding["provider_status"].as_str(),Some("success"|"partial"|"no_results")){"finding_retained"}else{finding["provider_status"].as_str().ok_or_else(invalid)?},"recorded_state":"finding_retained","reserved_local_requests":1,"budget_unit":"search_request","provider_post_admissions":1,"provider_charge_verified":false,"outbound_messages_sent":0,"replay_authorized":false,"evidence_basis":"retained_finding_not_new_execution"});
        for (key, v) in finding.as_object().ok_or_else(invalid)? {
            value[key] = v.clone();
        }
        return Ok(value);
    }
    Ok(
        json!({"request_id":request,"company_name":company,"status":if now>expires{"outcome_unknown"}else{"running"},"recorded_state":"dispatch_admitted","people":[],"errors":if now>expires{vec!["public_research_original_dispatch_unconfirmed"]}else{vec![]},"reserved_local_requests":1,"budget_unit":"search_request","provider_post_admissions":1,"provider_response_retained":false,"provider_charge_verified":false,"outbound_messages_sent":0,"replay_authorized":false,"evidence_basis":"retained_intent_not_new_execution"}),
    )
}
pub async fn admit(
    c: &mut PgConnection,
    input: Value,
    request: Uuid,
    settings: &Settings,
) -> Result<Admission> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = time(&at)?;
    let input = research_contract::normalize(Kind::PeopleQuery, input, now)?;
    let hash = crate::startup_catalog::identity::content_hash(&input);
    let old:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(key(request)).fetch_optional(&mut *tx).await.map_err(db)?;
    if let Some(old) = old {
        let old = old.ok_or_else(invalid)?;
        if old["input_hash"] != hash {
            return Err(Failure("public_research_request_conflict"));
        }
        let value = output(&old, request, now)?;
        tx.commit().await.map_err(db)?;
        return Ok(Admission::Retained(value));
    }
    let manual: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)")
            .bind(format!("people_import:{}", request.simple()))
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    if manual {
        return Err(Failure("public_research_request_conflict"));
    }
    settings.require(&input)?;
    let body = json!({"q":super::rules::query(&input,now)?,"num":input["limit"]});
    let company = company_in(&mut tx, &input).await?;
    let reservation = budget::reserve_in(
        &mut tx,
        "serper",
        &format!("people_{}", request.simple()),
        1,
        settings.monthly,
    )
    .await?;
    let invocation = Uuid::new_v4();
    let deadline = now + chrono::Duration::seconds(30);
    let journal = json!({"schema":1,"request_id":request,"invocation":invocation,"input_hash":hash,"configuration_hash":settings.context,"company":company,"provider_request":body,"input":input,"state":"dispatch_admitted","post_admissions":1,"reservation_id":reservation.id(),"month":reservation.month(),"reserved_local_requests":1,"budget_unit":"search_request","started_at":at,"expires_at":deadline.to_rfc3339(),"provider_response_retained":false});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key(request)).bind(&journal).fetch_optional(&mut *tx).await.map_err(db)?;
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(key(request))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if saved.as_ref() != Some(&journal) || actual.as_ref() != Some(&journal) {
        return Err(ack());
    }
    budget::assert_reserved_in(&mut tx, &reservation).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_research_commit_outcome_unknown"))?;
    let permission = if input["research_mode"] == "official_company" {
        input["company_domain"]
            .as_str()
            .and_then(|d| settings.domains.get(d))
            .cloned()
    } else {
        settings.permission.clone()
    };
    Ok(Admission::Original(Box::new(Claim {
        id: request,
        journal,
        reservation,
        grant: Some(Grant {
            id: request,
            invocation,
            context: settings.context.clone(),
            body,
            deadline,
            input,
            permission,
        }),
    })))
}
pub async fn retained(c: &mut PgConnection, request: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let old:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(request)).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("public_research_request_not_found"))?;
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let value = output(&old.ok_or_else(invalid)?, request, time(&at)?)?;
    tx.commit().await.map_err(db)?;
    Ok(value)
}
