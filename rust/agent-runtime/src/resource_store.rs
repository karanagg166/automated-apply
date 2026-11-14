//! Owner-only consistent read snapshots. No URL/resume fetch and no admission side effects.
use crate::resource_contract::{self, Operation};
use crate::{Failure, Result, profile_store, resources};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use std::collections::BTreeMap;
use uuid::Uuid;

fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
fn write_error(error: sqlx::Error) -> Failure {
    if error
        .as_database_error()
        .is_some_and(|e| e.is_unique_violation())
    {
        Failure("resource_conflict")
    } else {
        db(error)
    }
}
fn read_record(mut row: Value, evidence: bool) -> Result<Value> {
    use chrono::{DateTime, SecondsFormat, Utc};
    let object = row
        .as_object_mut()
        .ok_or(Failure("invalid_resource_record"))?;
    let mut result = if evidence {
        let mut body = object.clone();
        for key in ["id", "candidate_profile_id", "created_at", "updated_at"] {
            body.remove(key);
        }
        resource_contract::normalize(Operation::Evidence, Value::Object(body))
            .map_err(|_| Failure("invalid_resource_record"))?
    } else {
        let mut result = serde_json::Map::new();
        for key in ["resource_type", "label", "url", "source_type"] {
            let raw = object
                .get(key)
                .and_then(Value::as_str)
                .ok_or(Failure("invalid_resource_record"))?;
            if key == "resource_type" && !resources::LINK_KINDS.contains(&raw) && raw != "other" {
                return Err(Failure("invalid_resource_record"));
            }
            result.insert(key.into(), json!(raw.trim()));
        }
        for key in ["is_primary", "user_confirmed"] {
            result.insert(
                key.into(),
                json!(
                    object
                        .get(key)
                        .and_then(Value::as_bool)
                        .ok_or(Failure("invalid_resource_record"))?
                ),
            );
        }
        Value::Object(result)
    };
    for key in ["id", "candidate_profile_id"] {
        result[key] = json!(
            object
                .get(key)
                .and_then(Value::as_str)
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or(Failure("invalid_resource_record"))?
        );
    }
    for key in ["created_at", "updated_at"] {
        let at = object
            .get(key)
            .and_then(Value::as_str)
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .ok_or(Failure("invalid_resource_record"))?;
        result[key] = json!(at.with_timezone(&Utc).to_rfc3339_opts(
            if at.timestamp_subsec_micros() == 0 {
                SecondsFormat::Secs
            } else {
                SecondsFormat::Micros
            },
            true
        ));
    }
    Ok(result)
}
pub async fn list(
    connection: &mut PgConnection,
    evidence: bool,
    offset: i64,
    limit: i64,
    defaults: &BTreeMap<String, String>,
) -> Result<Value> {
    let mut transaction = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    let profile = profile_store::get(&mut transaction).await?.value;
    let id = profile["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let output = if evidence {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,candidate_profile_id,evidence_type,title,content,source_url,source_description,user_confirmed,project,created_at,updated_at FROM candidate_evidence WHERE candidate_profile_id=$1 ORDER BY created_at,id OFFSET $2 LIMIT $3) r").bind(id).bind(offset).bind(limit).fetch_all(&mut *transaction).await.map_err(db)?;
        let mut verified = Vec::new();
        let mut unverified = Vec::new();
        for row in rows {
            let row = read_record(row, true)?;
            if row["user_confirmed"] == true {
                verified.push(row);
            } else {
                unverified.push(row);
            }
        }
        json!({"verified":verified,"unverified":unverified,"offset":offset,"limit":limit})
    } else {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,candidate_profile_id,resource_type,label,url,is_primary,source_type,user_confirmed,created_at,updated_at FROM candidate_resources WHERE candidate_profile_id=$1 ORDER BY created_at,id OFFSET $2 LIMIT $3) r").bind(id).bind(offset).bind(limit).fetch_all(&mut *transaction).await.map_err(db)?;
        let rows = rows
            .into_iter()
            .map(|row| read_record(row, false))
            .collect::<Result<Vec<_>>>()?;
        let resolution:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,resource_type,label,url,is_primary,source_type,user_confirmed,updated_at,row_number() OVER (PARTITION BY resource_type ORDER BY is_primary DESC,user_confirmed DESC,created_at,id) AS position FROM candidate_resources WHERE candidate_profile_id=$1) r WHERE position<=101").bind(id).fetch_all(&mut *transaction).await.map_err(db)?;
        let resolution = resolution
            .into_iter()
            .map(|row| {
                serde_json::from_value::<resources::Resource>(row)
                    .map_err(|_| Failure("invalid_resource_record"))
            })
            .collect::<Result<Vec<_>>>()?;
        let links: Vec<_> = resources::LINK_KINDS
            .iter()
            .map(|kind| resources::resolved_link(&profile, &resolution, defaults, kind))
            .collect();
        json!({"resources":rows,"resolved_links":links,"offset":offset,"limit":limit})
    };
    transaction.commit().await.map_err(db)?;
    Ok(output)
}
pub async fn save_resource(
    connection: &mut PgConnection,
    input: Value,
    live: bool,
) -> Result<Value> {
    let values = resource_contract::normalize(Operation::Resource, input)?;
    let kind = values["resource_type"].as_str().unwrap();
    if let Some(field) = resources::standard_field(kind) {
        if !values["id"].is_null() || values["user_confirmed"] != true {
            return Err(Failure("standard_link_confirmation_required"));
        }
        if values["expected_profile_version"].is_null() {
            return Err(Failure("standard_link_version_required"));
        }
        let version = values["expected_profile_version"]
            .as_i64()
            .and_then(|n| i32::try_from(n).ok())
            .ok_or(Failure("profile_version_conflict"))?;
        let saved = profile_store::save(
            connection,
            json!({field:values["url"]}),
            Some(version),
            true,
            live,
        )
        .await?;
        return Ok(
            json!({"resource_type":kind,"url":saved.value[field],"source":"candidate_profile","resource_id":null,"user_confirmed":true}),
        );
    }
    let mut transaction = connection.begin().await.map_err(db)?;
    let profile: Uuid = sqlx::query_scalar(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
    )
    .fetch_optional(&mut *transaction)
    .await
    .map_err(db)?
    .ok_or(Failure("profile_not_found"))?;
    let row = if let Some(id) = values["id"].as_str() {
        let id = id.parse::<Uuid>().unwrap();
        // Lock and scope before mutation. An unowned UUID cannot cross profile boundaries.
        let owned: Option<Uuid> = sqlx::query_scalar(
            "SELECT id FROM candidate_resources WHERE id=$1 AND candidate_profile_id=$2 FOR UPDATE",
        )
        .bind(id)
        .bind(profile)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(db)?;
        if owned.is_none() {
            return Err(Failure("resource_not_found"));
        }
        sqlx::query_scalar::<_,Value>("UPDATE candidate_resources SET resource_type=$3::jsonb->>'resource_type',label=$3::jsonb->>'label',url=$3::jsonb->>'url',is_primary=($3::jsonb->>'is_primary')::boolean,source_type=$3::jsonb->>'source_type',user_confirmed=($3::jsonb->>'user_confirmed')::boolean,updated_at=CASE WHEN (resource_type,label,url,is_primary,source_type,user_confirmed) IS DISTINCT FROM ($3::jsonb->>'resource_type',$3::jsonb->>'label',$3::jsonb->>'url',($3::jsonb->>'is_primary')::boolean,$3::jsonb->>'source_type',($3::jsonb->>'user_confirmed')::boolean) THEN clock_timestamp() ELSE updated_at END WHERE id=$1 AND candidate_profile_id=$2 RETURNING to_jsonb(candidate_resources.*)").bind(id).bind(profile).bind(&values).fetch_one(&mut *transaction).await.map_err(write_error)?
    } else {
        sqlx::query_scalar::<_,Value>("WITH stamp AS (SELECT clock_timestamp() AS at) INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,is_primary,source_type,user_confirmed,created_at,updated_at) SELECT $1,$2,$3::jsonb->>'resource_type',$3::jsonb->>'label',$3::jsonb->>'url',($3::jsonb->>'is_primary')::boolean,$3::jsonb->>'source_type',($3::jsonb->>'user_confirmed')::boolean,at,at FROM stamp ON CONFLICT DO NOTHING RETURNING to_jsonb(candidate_resources.*)").bind(Uuid::new_v4()).bind(profile).bind(&values).fetch_optional(&mut *transaction).await.map_err(db)?.ok_or(Failure("resource_insert_conflict"))?
    };
    let output = read_record(row, false)?;
    transaction.commit().await.map_err(db)?;
    Ok(output)
}
pub async fn resolve_question(
    connection: &mut PgConnection,
    input: Value,
    defaults: &BTreeMap<String, String>,
) -> Result<Value> {
    let question = crate::link_resolver::question(input)?;
    let mut transaction = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    let profile = profile_store::get(&mut transaction).await?.value;
    let id = profile["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let resources = resolution_resources(&mut transaction, id).await?;
    let result = crate::link_resolver::resolve(&profile, &resources, defaults, &question);
    transaction.commit().await.map_err(db)?;
    Ok(result)
}
/// Reuse the saved inventory inside a caller-owned consistent snapshot; no fetch or new connection.
pub(crate) async fn resolution_resources(
    connection: &mut PgConnection,
    id: Uuid,
) -> Result<Vec<resources::Resource>> {
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,resource_type,label,url,is_primary,source_type,user_confirmed,updated_at,row_number() OVER (PARTITION BY resource_type ORDER BY is_primary DESC,user_confirmed DESC,created_at,id) AS position FROM candidate_resources WHERE candidate_profile_id=$1) r WHERE position<=101").bind(id).fetch_all(connection).await.map_err(db)?;
    rows.into_iter()
        .map(|row| {
            serde_json::from_value::<resources::Resource>(row)
                .map_err(|_| Failure("invalid_resource_record"))
        })
        .collect()
}
pub async fn save_evidence(
    connection: &mut PgConnection,
    id: Option<Uuid>,
    input: Value,
) -> Result<Value> {
    let values = resource_contract::normalize(
        if id.is_some() {
            Operation::Patch
        } else {
            Operation::Evidence
        },
        input,
    )?;
    let mut transaction = connection.begin().await.map_err(db)?;
    let profile: Uuid = sqlx::query_scalar(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
    )
    .fetch_optional(&mut *transaction)
    .await
    .map_err(db)?
    .ok_or(Failure("profile_not_found"))?;
    let row = if let Some(id) = id {
        let current:Value=sqlx::query_scalar("SELECT to_jsonb(e) FROM candidate_evidence e WHERE id=$1 AND candidate_profile_id=$2 FOR UPDATE").bind(id).bind(profile).fetch_optional(&mut *transaction).await.map_err(db)?.ok_or(Failure("evidence_not_found"))?;
        let complete = resource_contract::merge_evidence(current.clone(), values)?;
        let unchanged = complete
            .as_object()
            .unwrap()
            .iter()
            .all(|(key, value)| current.get(key) == Some(value));
        if unchanged {
            current
        } else {
            sqlx::query_scalar("UPDATE candidate_evidence SET title=$3::jsonb->>'title',content=$3::jsonb->>'content',source_url=$3::jsonb->>'source_url',source_description=$3::jsonb->>'source_description',user_confirmed=($3::jsonb->>'user_confirmed')::boolean,project=NULLIF($3::jsonb->'project','null'::jsonb),updated_at=clock_timestamp() WHERE id=$1 AND candidate_profile_id=$2 RETURNING to_jsonb(candidate_evidence.*)").bind(id).bind(profile).bind(&complete).fetch_one(&mut *transaction).await.map_err(db)?
        }
    } else {
        sqlx::query_scalar("WITH stamp AS (SELECT clock_timestamp() AS at) INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,source_url,source_description,user_confirmed,project,created_at,updated_at) SELECT $1,$2,$3::jsonb->>'evidence_type',$3::jsonb->>'title',$3::jsonb->>'content',$3::jsonb->>'source_url',$3::jsonb->>'source_description',($3::jsonb->>'user_confirmed')::boolean,NULLIF($3::jsonb->'project','null'::jsonb),at,at FROM stamp RETURNING to_jsonb(candidate_evidence.*)").bind(Uuid::new_v4()).bind(profile).bind(&values).fetch_one(&mut *transaction).await.map_err(db)?
    };
    let output = read_record(row, true)?;
    transaction.commit().await.map_err(db)?;
    Ok(output)
}

pub async fn inspect(
    connection: &mut PgConnection,
    selected: Option<Uuid>,
    readiness: bool,
    live: bool,
) -> Result<Value> {
    let mut transaction = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    let profile = match profile_store::get(&mut transaction).await {
        Ok(saved) => Some(saved.value),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    let mut saved = Vec::new();
    if let Some(profile) = &profile {
        let id = profile["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_profile_record"))?;
        // Never silently choose a primary from a truncated resource inventory.
        let rows: Vec<Value> = sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,resource_type,label,url,user_confirmed,is_primary,source_type,updated_at FROM candidate_resources WHERE candidate_profile_id=$1 ORDER BY created_at,id LIMIT 10001) r")
            .bind(id).fetch_all(&mut *transaction).await.map_err(db)?;
        if rows.len() > 10000 {
            return Err(Failure("resource_inventory_limit"));
        }
        for row in rows {
            saved.push(
                serde_json::from_value::<resources::Resource>(row)
                    .map_err(|_| Failure("invalid_resource_record"))?,
            );
        }
    }
    let output = if readiness {
        resources::assess_profile(profile, &saved, live)?
    } else {
        if profile.is_none() {
            return Err(Failure("profile_not_found"));
        }
        serde_json::to_value(resources::select_resume(&saved, selected)?)
            .map_err(|_| Failure("invalid_resource_record"))?
    };
    transaction.commit().await.map_err(db)?;
    Ok(output)
}
