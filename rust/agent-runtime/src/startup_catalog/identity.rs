//! Domain/source identity outweighs display names. Normalized observations remain immutable.
use crate::{
    Failure, Result,
    research_contract::{self, Kind},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn invalid() -> Failure {
    Failure("invalid_startup_identity_record")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_identity_database_error")
}
fn ack() -> Failure {
    Failure("startup_identity_write_ack_failed")
}
fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
pub fn identity_key(item: &Value) -> Result<String> {
    let value = if let Some(id) = item["source_company_id"].as_str().filter(|s| !s.is_empty()) {
        format!("id:{id}")
    } else if let Some(domain) = item["domain"].as_str().filter(|s| !s.is_empty()) {
        format!("domain:{domain}")
    } else {
        format!("url:{}", item["source_url"].as_str().ok_or_else(invalid)?)
    };
    Ok(hash(&value))
}
pub fn content_hash(item: &Value) -> String {
    hash(&crate::python_json::serialize(item, false, true))
}
pub struct Company {
    pub id: Uuid,
    pub created: bool,
}
async fn company_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=1048576 THEN to_jsonb(c) ELSE NULL END FROM companies c WHERE id=$1 FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("startup_catalog_not_found"))?;
    let value = value.ok_or_else(invalid)?;
    if !value["metadata"].is_object() {
        return Err(invalid());
    }
    Ok(value)
}
pub(crate) async fn resolve_in(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
) -> Result<Company> {
    let source = item["source"].as_str().ok_or_else(invalid)?;
    let identity = identity_key(item)?;
    let prior:Vec<Uuid>=sqlx::query_scalar("SELECT DISTINCT company_id FROM company_source_observations WHERE source=$1 AND identity_key=$2 ORDER BY company_id LIMIT 2").bind(source).bind(&identity).fetch_all(&mut **tx).await.map_err(db)?;
    if prior.len() > 1 {
        return Err(Failure("startup_source_identity_ambiguous"));
    }
    let domains: Vec<Uuid> = if let Some(domain) = item["domain"].as_str() {
        sqlx::query_scalar("SELECT id FROM companies WHERE domain=$1 ORDER BY id LIMIT 2")
            .bind(domain)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?
    } else {
        vec![]
    };
    if domains.len() > 1 {
        return Err(Failure("startup_company_domain_ambiguous"));
    }
    let mut ids = prior
        .iter()
        .chain(domains.iter())
        .copied()
        .collect::<Vec<_>>();
    ids.sort();
    ids.dedup();
    for id in &ids {
        company_in(tx, *id).await?;
    }
    if let Some(id) = prior.first().copied() {
        let before = company_in(tx, id).await?;
        if item["source_company_id"].is_null()
            && item["domain"].is_null()
            && crate::contacts::enrichment::identity::folded(
                before["name"].as_str().ok_or_else(invalid)?,
            ) != crate::contacts::enrichment::identity::folded(
                item["name"].as_str().ok_or_else(invalid)?,
            )
        {
            return Err(Failure("startup_unqualified_company_url_conflict"));
        }
        if domains.first().is_some_and(|other| *other != id)
            || !item["domain"].is_null()
                && !before["domain"].is_null()
                && before["domain"] != item["domain"]
        {
            return Err(Failure("startup_source_company_domain_conflict"));
        }
        if !item["domain"].is_null() && before["domain"].is_null() {
            if crate::contacts::rules::truthy(&before["metadata"]["identity_review_required"]) {
                return Err(Failure("startup_company_identity_review_required"));
            }
            let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
            let mut expected = before.clone();
            expected["domain"] = item["domain"].clone();
            expected["updated_at"] = stamp.clone();
            let saved:Option<Value>=sqlx::query_scalar("UPDATE companies c SET domain=$1,updated_at=($2::jsonb#>>'{}')::timestamptz WHERE id=$3 AND domain IS NULL RETURNING to_jsonb(c)").bind(item["domain"].as_str()).bind(&stamp).bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
            let saved = saved.ok_or_else(ack)?;
            if saved["updated_at"] != stamp {
                let end: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
                    .fetch_one(&mut **tx)
                    .await
                    .map_err(db)?;
                let parse = |v: &Value| {
                    chrono::DateTime::parse_from_rfc3339(v.as_str().ok_or_else(invalid)?)
                        .map_err(|_| invalid())
                };
                let at = parse(&saved["updated_at"])?;
                if at < parse(&stamp)? || at > parse(&end)? {
                    return Err(ack());
                }
                expected["updated_at"] = saved["updated_at"].clone();
            }
            if saved != expected || company_in(tx, id).await? != expected {
                return Err(ack());
            }
        }
        return Ok(Company { id, created: false });
    }
    if let Some(id) = domains.first().copied() {
        return Ok(Company { id, created: false });
    }
    let id = Uuid::new_v4();
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let expected = json!({"id":id,"name":item["name"],"domain":item["domain"],"linkedin_url":null,"email_pattern":null,"is_catch_all":false,"metadata":{},"created_at":stamp,"updated_at":stamp});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO companies AS c(id,name,domain,linkedin_url,email_pattern,is_catch_all,metadata,created_at,updated_at) VALUES($1,$2::jsonb->>'name',$2::jsonb->>'domain',NULL,NULL,false,'{}',($2::jsonb->>'created_at')::timestamptz,($2::jsonb->>'updated_at')::timestamptz) RETURNING to_jsonb(c)").bind(id).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) || company_in(tx, id).await? != expected {
        return Err(ack());
    }
    Ok(Company { id, created: true })
}
pub(crate) async fn ingest_in(
    tx: &mut Transaction<'_, Postgres>,
    item: Value,
    run_id: Option<Uuid>,
) -> Result<Value> {
    let company = resolve_in(tx, &item).await?;
    let key = identity_key(&item)?;
    let digest = content_hash(&item);
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(($1::jsonb#>>'{}')::timestamptz)")
        .bind(&item["observed_at"])
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let prior:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(o)::text)<=1048576 THEN to_jsonb(o) ELSE NULL END FROM company_source_observations o WHERE source=$1 AND identity_key=$2 AND content_hash=$3 FOR UPDATE").bind(item["source"].as_str()).bind(&key).bind(&digest).fetch_optional(&mut **tx).await.map_err(db)?;
    if let Some(prior) = prior {
        let prior = prior.ok_or_else(invalid)?;
        if prior["company_id"] != json!(company.id)
            || prior["observed_at"] != at
            || prior["attributes"] != item
            || prior["source_url"] != item["source_url"]
            || prior["verification_status"] != item["verification_status"]
        {
            return Err(Failure("startup_company_observation_replay_conflict"));
        }
        return Ok(
            json!({"company_id":company.id,"observation_id":prior["id"],"created":false,"company_created":false,"preserved_original":true}),
        );
    }
    if let Some(run_id) = run_id {
        let found:Option<Uuid>=sqlx::query_scalar("SELECT id FROM discovery_runs WHERE id=$1 AND starts_with(source,'startup_') FOR SHARE").bind(run_id).fetch_optional(&mut **tx).await.map_err(db)?;
        if found.is_none() {
            return Err(Failure("startup_catalog_run_not_found"));
        }
    }
    let id = Uuid::new_v4();
    let expected = json!({"id":id,"company_id":company.id,"run_id":run_id,"source":item["source"],"identity_key":key,"content_hash":digest,"source_url":item["source_url"],"observed_at":at,"attributes":item,"verification_status":item["verification_status"]});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO company_source_observations AS o(id,company_id,run_id,source,identity_key,content_hash,source_url,observed_at,attributes,verification_status) SELECT x.id,x.company_id,x.run_id,x.source,x.identity_key,x.content_hash,x.source_url,x.observed_at,x.attributes,x.verification_status FROM jsonb_populate_record(NULL::company_source_observations,$1) x ON CONFLICT DO NOTHING RETURNING to_jsonb(o)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(o) FROM company_source_observations o WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if saved.as_ref() != Some(&expected) || actual.as_ref() != Some(&expected) {
        return Err(ack());
    }
    Ok(
        json!({"company_id":company.id,"observation_id":id,"created":true,"company_created":company.created,"preserved_original":false}),
    )
}
pub async fn ingest(c: &mut PgConnection, item: Value, run_id: Option<Uuid>) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = chrono::DateTime::parse_from_rfc3339(now.as_str().ok_or_else(invalid)?)
        .map_err(|_| invalid())?
        .to_utc();
    let item = research_contract::normalize(Kind::CompanyObservation, item, now)?;
    let result = ingest_in(&mut tx, item, run_id).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_identity_commit_outcome_unknown"))?;
    Ok(result)
}
