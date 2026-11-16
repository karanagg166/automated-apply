//! Saved company people, public observations and jobs. No discovery or owner mutation.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
#[derive(Clone, Copy)]
pub enum Route {
    People(Uuid),
    Evidence(Uuid),
    Jobs(Uuid),
}
pub fn route(path: &str) -> Option<Route> {
    if let Some(tail) = path.strip_prefix("/api/v1/companies/") {
        return tail
            .strip_suffix("/people")
            .and_then(|id| id.parse().ok())
            .map(Route::People);
    }
    let tail = path.strip_prefix("/api/v1/startups/")?;
    let (id, action) = tail.split_once('/')?;
    let id = id.parse().ok()?;
    match action {
        "evidence" => Some(Route::Evidence(id)),
        "jobs" => Some(Route::Jobs(id)),
        _ => None,
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("company_saved_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_company_saved_record")
}
pub fn page(query: Option<&str>) -> Result<(i64, i64)> {
    let mut limit = 100;
    let mut offset = 0;
    let mut seen = std::collections::BTreeSet::new();
    if let Some(query) = query {
        if query.len() > 1024 {
            return Err(Failure("invalid_company_saved_query"));
        }
        let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
            .map_err(|_| Failure("invalid_company_saved_query"))?;
        for (key, value) in url.query_pairs() {
            if !seen.insert(key.to_string()) {
                return Err(Failure("invalid_company_saved_query"));
            }
            match key.as_ref() {
                "limit" => {
                    limit = crate::profile_contract::pagination_integer(json!(value), 1, 100)
                        .map_err(|_| Failure("invalid_company_saved_query"))?
                }
                "offset" => {
                    offset = crate::profile_contract::pagination_integer(json!(value), 0, 100000)
                        .map_err(|_| Failure("invalid_company_saved_query"))?
                }
                _ => return Err(Failure("invalid_company_saved_query")),
            }
        }
    }
    Ok((limit, offset))
}
fn date(value: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str().ok_or_else(invalid)?)
        .map(|d| d.to_utc())
        .map_err(|_| invalid())
}
fn stamp(at: DateTime<Utc>) -> String {
    at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        false,
    )
}
fn url(value: &Value) -> Result<Value> {
    if value.is_null() {
        return Ok(Value::Null);
    }
    Ok(json!(
        crate::resources::public_https(value.as_str().ok_or_else(invalid)?).ok_or_else(invalid)?
    ))
}
fn bounded_text(value: &Value, max: usize) -> Result<Value> {
    if !value.is_null() && !value.as_str().is_some_and(|s| s.chars().count() <= max) {
        return Err(invalid());
    }
    Ok(value.clone())
}
pub fn person(value: Value, now: DateTime<Utc>) -> Result<Value> {
    if !value.is_object() {
        return Err(invalid());
    }
    let mut result = json!({});
    for key in ["name", "role"] {
        result[key] = bounded_text(&value[key], 255)?;
    }
    result["source"] = bounded_text(&value["source"], 100)?;
    let profile = value["linkedin_url"]
        .as_str()
        .and_then(crate::contacts::enrichment::lookups::linkedin)
        .ok_or_else(invalid)?;
    result["linkedin_url"] = json!(profile);
    result["evidence_url"] = url(&value["evidence_url"])?;
    let at = date(&value["observed_at"])?;
    let valid = at <= now;
    let status = value["verification_status"]
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "human_confirmed" | "source_reported" | "requires_review"
            )
        })
        .ok_or_else(invalid)?;
    result["recorded_verification_status"] = json!(status);
    result["verification_status"] = json!(if valid { status } else { "requires_review" });
    result["observed_at"] = json!(stamp(at));
    result["stale"] = json!(!valid || at < now - chrono::Duration::days(90));
    result["evidence"] =
        json!({"text":bounded_text(&value["evidence"]["text"],4000)?,"outreach_mode":"manual"});
    result["outreach_mode"] = json!("manual");
    result["verification_basis"] = json!("saved_record_not_current_probe");
    result["live_verified"] = json!(false);
    result["email_send_ready"] = json!(false);
    Ok(result)
}
pub(crate) fn attributes(value: &Value) -> Result<Value> {
    let object = value.as_object().ok_or_else(invalid)?;
    let mut result = json!({});
    for key in [
        "name",
        "domain",
        "source",
        "source_company_id",
        "country",
        "location",
        "industry",
        "stage",
        "yc_batch",
        "product_category",
        "remote_policy",
        "team_size_band",
        "hiring_statement",
        "verification_status",
    ] {
        if let Some(v) = object.get(key) {
            result[key] = bounded_text(v, 255)?;
        }
    }
    if let Some(v) = object.get("description") {
        result["description"] = bounded_text(v, 4000)?;
    }
    for key in ["source_url", "permission_evidence_url", "careers_url"] {
        if let Some(v) = object.get(key) {
            result[key] = url(v)?;
        }
    }
    if let Some(v) = object.get("observed_at") {
        date(v)?;
        result["observed_at"] = v.clone();
    }
    for key in ["historical", "authoritative_statement"] {
        if let Some(v) = object.get(key) {
            if !v.is_boolean() {
                return Err(invalid());
            }
            result[key] = v.clone();
        }
    }
    for (key, min, max) in [
        ("employee_count", 1, 10000000),
        ("founding_year", 1800, 2100),
    ] {
        if let Some(v) = object.get(key) {
            if !v.is_null() && !v.as_i64().is_some_and(|n| (min..=max).contains(&n)) {
                return Err(invalid());
            }
            result[key] = v.clone();
        }
    }
    if let Some(v) = object.get("technology_stack") {
        if !v.as_array().is_some_and(|a| {
            a.len() <= 30
                && a.iter()
                    .all(|v| v.as_str().is_some_and(|s| s.chars().count() <= 200))
        }) {
            return Err(invalid());
        }
        result["technology_stack"] = v.clone();
    }
    Ok(result)
}
pub fn observation(value: Value, now: DateTime<Utc>) -> Result<Value> {
    let id = value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let at = date(&value["observed_at"])?;
    let valid = at <= now;
    let status = value["verification_status"]
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "human_confirmed" | "source_reported" | "requires_review"
            )
        })
        .ok_or_else(invalid)?;
    let source = value["source"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 100)
        .ok_or_else(invalid)?;
    Ok(
        json!({"id":id,"source":source,"source_url":url(&value["source_url"] )?,"observed_at":stamp(at),"verification_status":if valid{status}else{"requires_review"},"recorded_verification_status":status,"attributes":attributes(&value["attributes"] )?,"stale":!valid||at<now-chrono::Duration::days(180),"verification_basis":"saved_record_not_current_probe","live_verified":false}),
    )
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    if method != "GET" {
        return Err(Failure("company_saved_method_not_allowed"));
    }
    if !body.is_empty() {
        return Err(Failure("invalid_company_saved_query"));
    }
    let (limit, offset) = page(query)?;
    let id = match route {
        Route::People(id) | Route::Evidence(id) | Route::Jobs(id) => id,
    };
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let found: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM companies WHERE id=$1)")
        .bind(id)
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if !found {
        return Err(Failure("company_saved_not_found"));
    }
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = date(&now)?;
    let result = if matches!(route, Route::Jobs(_)) {
        crate::job_catalog::company_in(&mut tx, id, limit, offset).await?
    } else {
        let (table, order, projection, key) = if matches!(route, Route::People(_)) {
            (
                "discovered_people",
                "observed_at DESC,id",
                "jsonb_build_object('name',name,'role',role,'linkedin_url',linkedin_url,'evidence_url',evidence_url,'source',source,'observed_at',observed_at,'verification_status',verification_status,'evidence',jsonb_build_object('text',evidence::jsonb->'text'))",
                "people",
            )
        } else {
            (
                "company_source_observations",
                "observed_at DESC,id",
                "jsonb_build_object('id',id,'source',source,'source_url',source_url,'observed_at',observed_at,'verification_status',verification_status,'attributes',attributes)",
                "observations",
            )
        };
        let total: i64 =
            sqlx::query_scalar(&format!("SELECT count(*) FROM {table} WHERE company_id=$1"))
                .bind(id)
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
        let rows:Vec<Option<Value>>=sqlx::query_scalar(&format!("WITH selected AS (SELECT {projection} AS value,observed_at,id FROM {table} WHERE company_id=$1 ORDER BY {order} LIMIT $2 OFFSET $3) SELECT CASE WHEN octet_length(value::text)<=262144 THEN value ELSE NULL END FROM selected ORDER BY {order}")).bind(id).bind(limit).bind(offset).fetch_all(&mut *tx).await.map_err(db)?;
        let mut bytes = 0;
        let mut records = Vec::new();
        for row in rows {
            let row = row.ok_or_else(invalid)?;
            bytes += row.to_string().len();
            if bytes > 8 * 1024 * 1024 {
                return Err(Failure("company_saved_projection_limit"));
            }
            records.push(if matches!(route, Route::People(_)) {
                person(row, now)?
            } else {
                observation(row, now)?
            });
        }
        let count = records.len() as i64;
        let mut value = json!({"total":total,"limit":limit,"offset":offset,"has_more":offset+count<total,"evidence_basis":"saved_local_records"});
        value[key] = json!(records);
        value
    };
    tx.commit()
        .await
        .map_err(|_| Failure("company_saved_read_commit_failed"))?;
    Ok(result)
}
