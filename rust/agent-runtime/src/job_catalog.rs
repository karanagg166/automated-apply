//! Saved job screen only. Shortlisting conveys no application/admission authority.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

pub(crate) const JOBS: &str = "/api/v1/jobs";
pub(crate) enum Route<'a> {
    List,
    Detail(&'a str),
    Shortlist(&'a str),
}
pub(crate) fn route(path: &str) -> Option<Route<'_>> {
    if path == JOBS {
        return Some(Route::List);
    }
    if let Some(id) = path
        .strip_prefix("/api/v1/jobs/")
        .filter(|id| !id.is_empty() && !id.contains('/'))
    {
        return Some(Route::Detail(id));
    }
    path.strip_prefix("/api/v1/dashboard/jobs/")?
        .strip_suffix("/shortlist")
        .filter(|id| !id.is_empty() && !id.contains('/'))
        .map(Route::Shortlist)
}
fn valid_status(value: &str) -> bool {
    matches!(
        value,
        "discovered" | "reviewed" | "shortlisted" | "applied" | "rejected" | "archived"
    )
}
pub(crate) struct Page {
    pub limit: i64,
    pub offset: i64,
    pub status: Option<String>,
}
impl Page {
    pub(crate) fn parse(query: Option<&str>) -> Result<Self> {
        let mut raw = std::collections::BTreeMap::new();
        if let Some(query) = query {
            if query.len() > 4096 {
                return Err(Failure("invalid_job_page"));
            }
            // Legacy read-only queries use the last scalar and ignore unknown keys.
            let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
                .map_err(|_| Failure("invalid_job_page"))?;
            for (k, v) in url.query_pairs() {
                raw.insert(k.into_owned(), v.into_owned());
            }
        }
        let integer = |key: &str, default: i64, min: i64, max: i64| -> Result<i64> {
            raw.get(key)
                .map(|v| {
                    crate::profile_contract::pagination_integer(json!(v), min, max)
                        .map_err(|_| Failure("invalid_job_page"))
                })
                .unwrap_or(Ok(default))
        };
        let limit = integer("limit", 50, 1, 100)?;
        let offset = integer("offset", 0, 0, 100000)?;
        let status = raw.get("status").cloned();
        if status.as_deref().is_some_and(|s| !valid_status(s)) {
            return Err(Failure("invalid_job_status"));
        }
        Ok(Self {
            limit,
            offset,
            status,
        })
    }
}
macro_rules! projection { () => { "jsonb_build_object('id',id,'title',title,'job_url',job_url,'source_platform',source_platform,'company_id',company_id,'location',location,'is_remote',is_remote,'experience_level',experience_level,'salary_range',salary_range,'skills_required',skills_required,'description',description,'match_score',match_score,'match_explanation',match_explanation,'status',status,'date_posted',date_posted,'created_at',created_at,'updated_at',updated_at)" }; }
fn db(_: sqlx::Error) -> Failure {
    Failure("saved_jobs_database_error")
}
fn read(mut value: Value) -> Result<Value> {
    let invalid = Failure("invalid_catalog_job_record");
    for (key, min, max) in [
        ("title", 1, 255),
        ("job_url", 0, usize::MAX),
        ("source_platform", 0, 100),
    ] {
        let v = value[key].as_str().ok_or(invalid)?;
        let n = v.chars().count();
        if n < min || n > max {
            return Err(invalid);
        }
    }
    for (key, max) in [
        ("location", 255),
        ("experience_level", 50),
        ("salary_range", 100),
        ("description", usize::MAX),
        ("match_explanation", usize::MAX),
    ] {
        if !value[key].is_null() && value[key].as_str().is_none_or(|s| s.chars().count() > max) {
            return Err(invalid);
        }
    }
    if value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .is_none()
        || (!value["company_id"].is_null()
            && value["company_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .is_none())
        || !value["is_remote"].is_boolean()
        || !value["skills_required"]
            .as_array()
            .is_some_and(|a| a.iter().all(Value::is_string))
        || !value["status"].as_str().is_some_and(valid_status)
    {
        return Err(invalid);
    }
    if !value["match_score"].is_null() {
        let n = value["match_score"]
            .as_f64()
            .filter(|n| n.is_finite() && (0.0..=100.0).contains(n))
            .ok_or(invalid)?;
        value["match_score"] = json!(n);
    }
    for key in ["created_at", "updated_at", "date_posted"] {
        if key == "date_posted" && value[key].is_null() {
            continue;
        }
        let date = chrono::DateTime::parse_from_rfc3339(value[key].as_str().ok_or(invalid)?)
            .map_err(|_| invalid)?
            .with_timezone(&chrono::Utc);
        use chrono::Timelike;
        let precision = if date.nanosecond() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        };
        value[key] = json!(date.to_rfc3339_opts(precision, true));
    }
    Ok(value)
}
/// Saved company screen shares the original job DTO projection and normalization.
pub(crate) async fn company_in(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    company: Uuid,
    limit: i64,
    offset: i64,
) -> Result<Value> {
    let total: i64 = sqlx::query_scalar("SELECT count(*) FROM jobs WHERE company_id=$1")
        .bind(company)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let rows:Vec<Option<Value>>=sqlx::query_scalar(concat!("WITH selected AS (SELECT ",projection!()," AS value,last_observed_at,id FROM jobs WHERE company_id=$1 ORDER BY last_observed_at DESC NULLS LAST,id LIMIT $2 OFFSET $3) SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM selected ORDER BY last_observed_at DESC NULLS LAST,id")).bind(company).bind(limit).bind(offset).fetch_all(&mut **tx).await.map_err(db)?;
    let mut bytes = 0;
    let mut jobs = Vec::new();
    for value in rows {
        let value = value.ok_or(Failure("invalid_catalog_job_record"))?;
        bytes += value.to_string().len();
        if bytes > 8 * 1024 * 1024 {
            return Err(Failure("company_saved_projection_limit"));
        }
        jobs.push(read(value)?);
    }
    let count = jobs.len() as i64;
    Ok(
        json!({"jobs":jobs,"total":total,"limit":limit,"offset":offset,"has_more":offset+count<total,"evidence_basis":"saved_local_records"}),
    )
}
pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    page: &Page,
) -> Result<Value> {
    match route(path) {
        Some(Route::List) if method == "GET" => {
            let rows: Vec<Value> = sqlx::query_scalar(concat!("SELECT ",projection!()," FROM jobs WHERE ($3::text IS NULL OR status=$3) ORDER BY created_at DESC,id LIMIT $1 OFFSET $2"))
                .bind(page.limit)
                .bind(page.offset)
                .bind(&page.status)
                .fetch_all(connection)
                .await
                .map_err(db)?;
            Ok(json!(
                rows.into_iter().map(read).collect::<Result<Vec<_>>>()?
            ))
        }
        Some(Route::Detail(id)) if method == "GET" => {
            let id = id.parse::<Uuid>().map_err(|_| Failure("invalid_job_id"))?;
            let row: Option<Value> =
                sqlx::query_scalar(concat!("SELECT ", projection!(), " FROM jobs WHERE id=$1"))
                    .bind(id)
                    .fetch_optional(connection)
                    .await
                    .map_err(db)?;
            read(row.ok_or(Failure("saved_record_not_found"))?)
        }
        Some(Route::Shortlist(id)) if method == "POST" => {
            shortlist(
                connection,
                id.parse().map_err(|_| Failure("invalid_job_id"))?,
            )
            .await
        }
        Some(Route::Shortlist(_)) => Err(Failure("match_method_not_allowed")),
        Some(_) => Err(Failure("resource_read_method_not_allowed")),
        None => Err(Failure("owner_route_not_found")),
    }
}
async fn shortlist(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    let state: Option<String> =
        sqlx::query_scalar("SELECT status FROM jobs WHERE id=$1 FOR UPDATE")
            .bind(id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    let error = match state.as_deref() {
        None => Some(Failure("job_not_found")),
        Some("discovered" | "reviewed" | "shortlisted") => None,
        _ => Some(Failure("job_shortlist_conflict")),
    };
    if let Some(error) = error {
        tx.rollback().await.map_err(db)?;
        return Err(error);
    }
    if state.as_deref() != Some("shortlisted") {
        let changed = sqlx::query(
            "UPDATE jobs SET status='shortlisted',updated_at=clock_timestamp() WHERE id=$1",
        )
        .bind(id)
        .execute(&mut *tx)
        .await
        .map_err(db)?
        .rows_affected();
        if changed != 1 {
            tx.rollback().await.map_err(db)?;
            return Err(Failure("job_shortlist_write_conflict"));
        }
    }
    tx.commit().await.map_err(db)?;
    Ok(json!({"id":id,"status":"shortlisted"}))
}
