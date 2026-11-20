//! Saved job screen only. Shortlisting conveys no application/admission authority.
use crate::{Failure, Result, configuration::Configuration};
use automated_apply_domain::{
    matching::{Company, Listing, Profile, discovery_match},
    text::folded,
};
use chrono::{DateTime, Duration, SecondsFormat, Timelike, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::{BTreeMap, HashMap};
use uuid::Uuid;

pub(crate) const JOBS: &str = "/api/v1/jobs";
pub(crate) const SEARCH: &str = "/api/v1/jobs/search";
pub(crate) enum Route<'a> {
    List,
    Search,
    Detail(&'a str),
    Shortlist(&'a str),
}
pub(crate) fn route(path: &str) -> Option<Route<'_>> {
    if path == JOBS {
        return Some(Route::List);
    }
    if path == SEARCH {
        return Some(Route::Search);
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

pub(crate) struct SearchQuery {
    page: i64,
    limit: i64,
    platform: Option<String>,
    role: Option<String>,
    skill: Option<String>,
    application_status: String,
    location: Option<String>,
    remote_type: Option<String>,
    employment_type: Option<String>,
    experience_level: Option<String>,
    country: Option<String>,
    published_within_days: Option<i64>,
    company_size_band: Option<String>,
    approved_experience_fit: bool,
    minimum_match_score: Option<f64>,
    max_age_days: Option<i64>,
    sort: String,
    rank: bool,
    exclude_preferences: bool,
}

impl SearchQuery {
    pub(crate) fn parse(query: Option<&str>) -> Result<Self> {
        let invalid = || Failure("invalid_job_search");
        let mut raw = BTreeMap::new();
        if let Some(query) = query {
            if query.len() > 8192 {
                return Err(invalid());
            }
            let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
                .map_err(|_| invalid())?;
            for (k, v) in url.query_pairs() {
                raw.insert(k.into_owned(), v.into_owned());
            }
        }
        let int_opt = |key: &str, min: i64, max: i64| -> Result<Option<i64>> {
            raw.get(key)
                .filter(|v| !v.is_empty())
                .map(|v| {
                    crate::profile_contract::pagination_integer(json!(v), min, max)
                        .map_err(|_| invalid())
                })
                .transpose()
        };
        let str_opt = |key: &str, min: usize, max: usize| -> Result<Option<String>> {
            match raw.get(key) {
                None => Ok(None),
                Some(v) if v.is_empty() => Ok(None),
                Some(v) => {
                    let count = v.chars().count();
                    if count < min || count > max {
                        return Err(invalid());
                    }
                    Ok(Some(v.clone()))
                }
            }
        };
        let bool_val = |key: &str, default: bool| -> Result<bool> {
            match raw.get(key).map(|s| s.to_ascii_lowercase()).as_deref() {
                None | Some("") => Ok(default),
                Some("true" | "1" | "yes" | "on") => Ok(true),
                Some("false" | "0" | "no" | "off") => Ok(false),
                _ => Err(invalid()),
            }
        };

        let page = int_opt("page", 1, 10000)?.unwrap_or(1);
        let limit = int_opt("limit", 1, 100)?.unwrap_or(20);
        let application_status =
            str_opt("application_status", 1, 40)?.unwrap_or_else(|| "all".into());
        if !matches!(
            application_status.as_str(),
            "all"
                | "not_applied"
                | "shortlisted"
                | "packet_prepared"
                | "applied"
                | "interview"
                | "rejected"
        ) {
            return Err(invalid());
        }
        let remote_type = str_opt("remote_type", 1, 20)?;
        if remote_type
            .as_deref()
            .is_some_and(|v| !matches!(v, "remote" | "hybrid" | "onsite" | "unknown"))
        {
            return Err(invalid());
        }
        let company_size_band = str_opt("company_size_band", 1, 20)?;
        if company_size_band
            .as_deref()
            .is_some_and(|v| !matches!(v, "2-10" | "11-50"))
        {
            return Err(invalid());
        }
        let sort = str_opt("sort", 1, 20)?.unwrap_or_else(|| "freshness".into());
        if !matches!(sort.as_str(), "freshness" | "match" | "oldest") {
            return Err(invalid());
        }
        let minimum_match_score = raw
            .get("minimum_match_score")
            .filter(|v| !v.is_empty())
            .map(|v| {
                v.parse::<f64>()
                    .ok()
                    .filter(|n| n.is_finite() && (0.0..=100.0).contains(n))
                    .ok_or_else(invalid)
            })
            .transpose()?;

        Ok(Self {
            page,
            limit,
            platform: str_opt("platform", 1, 100)?,
            role: str_opt("role", 1, 200)?,
            skill: str_opt("skill", 1, 100)?,
            application_status,
            location: str_opt("location", 1, 200)?,
            remote_type,
            employment_type: str_opt("employment_type", 1, 50)?,
            experience_level: str_opt("experience_level", 1, 50)?,
            country: str_opt("country", 2, 100)?,
            published_within_days: int_opt("published_within_days", 1, 3650)?,
            company_size_band,
            approved_experience_fit: bool_val("approved_experience_fit", false)?,
            minimum_match_score,
            max_age_days: int_opt("max_age_days", 1, 3650)?,
            sort,
            rank: bool_val("rank", false)?,
            exclude_preferences: bool_val("exclude_preferences", true)?,
        })
    }
}

fn format_ts(value: Value) -> Result<Value> {
    if value.is_null() {
        return Ok(Value::Null);
    }
    let raw = value
        .as_str()
        .ok_or(Failure("invalid_catalog_job_record"))?;
    let date = DateTime::parse_from_rfc3339(raw)
        .map_err(|_| Failure("invalid_catalog_job_record"))?
        .with_timezone(&Utc);
    let precision = if date.nanosecond() == 0 {
        SecondsFormat::Secs
    } else {
        SecondsFormat::Micros
    };
    Ok(json!(date.to_rfc3339_opts(precision, true)))
}

fn experience_fit(job: &Value, approved_years: Option<f64>) -> &'static str {
    let Some(years) = approved_years else {
        return "unknown";
    };
    let meta = &job["discovery_metadata"];
    let min_years = meta["experience_min_years"].as_f64();
    let max_years = meta["experience_max_years"].as_f64();
    let Some(min_years) = min_years.filter(|n| n.is_finite() && *n >= 0.0) else {
        return "unknown";
    };
    if let Some(max_years) = max_years
        && (!max_years.is_finite() || max_years < min_years)
    {
        return "unknown";
    }
    if years < min_years {
        return "below_minimum";
    }
    if max_years.is_some_and(|max| years > max) {
        return "outside_published_range";
    }
    "within_published_range"
}

pub(crate) async fn search(
    connection: &mut PgConnection,
    query: &SearchQuery,
    config: &Configuration,
) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let result = search_in(&mut tx, query, config, now).await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}

async fn search_in(
    tx: &mut Transaction<'_, Postgres>,
    query: &SearchQuery,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let platform = if let Some(raw) = query.platform.as_deref() {
        let normalized = raw.trim().to_ascii_lowercase();
        let entry = config.sources.job(&normalized, now)?;
        Some(
            entry["id"]
                .as_str()
                .unwrap_or(normalized.as_str())
                .to_owned(),
        )
    } else {
        None
    };

    let needs_profile = query.rank
        || query.sort == "match"
        || query.minimum_match_score.is_some()
        || query.exclude_preferences;
    let saved_profile: Option<Value> = if needs_profile || query.approved_experience_fit {
        sqlx::query_scalar(
            "SELECT jsonb_build_object(
                'id', id,
                'version', version,
                'verified_skills', verified_skills,
                'verified_experience_years', verified_experience_years::double precision,
                'preferences', preferences
            ) FROM candidate_profiles WHERE singleton_key='primary' LIMIT 1",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
    } else {
        None
    };
    if saved_profile.is_none()
        && (query.rank || query.sort == "match" || query.minimum_match_score.is_some())
    {
        return Err(Failure("profile_required_for_ranking"));
    }
    let parsed_profile: Option<Profile> = saved_profile
        .as_ref()
        .map(|v| serde_json::from_value(v.clone()).map_err(|_| Failure("invalid_profile_record")))
        .transpose()?;

    let approved_years = if query.approved_experience_fit {
        let confirmation: Option<Value> = sqlx::query_scalar(
            "SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
        let confirmed = saved_profile
            .as_ref()
            .zip(confirmation.as_ref())
            .is_some_and(|(p, c)| {
                c["profile_id"] == p["id"]
                    && c["profile_version"] == p["version"]
                    && c["confirmed_at"].as_str().is_some_and(|s| !s.is_empty())
            });
        let years = if confirmed {
            saved_profile
                .as_ref()
                .and_then(|p| p["verified_experience_years"].as_f64())
                .filter(|n| n.is_finite())
        } else {
            None
        };
        if years.is_none() {
            return Err(Failure("approved_experience_required"));
        }
        years
    } else {
        None
    };

    let published_after = query
        .published_within_days
        .map(|days| now - Duration::days(days));
    let observed_after = query.max_age_days.map(|days| now - Duration::days(days));
    let role_lower = query.role.as_deref().map(|s| s.to_lowercase());
    let location_lower = query.location.as_deref().map(|s| s.to_lowercase());
    let exp_lower = query.experience_level.as_deref().map(|s| s.to_lowercase());

    let rows: Vec<(Value, Option<Value>)> = sqlx::query_as(
        "SELECT
            jsonb_build_object(
                'id', j.id,
                'title', j.title,
                'job_url', j.job_url,
                'source_platform', j.source_platform,
                'company_id', j.company_id,
                'location', j.location,
                'is_remote', coalesce(j.is_remote, false),
                'experience_level', j.experience_level,
                'salary_range', j.salary_range,
                'skills_required', coalesce(j.skills_required, ARRAY[]::text[]),
                'description', j.description,
                'match_score', j.match_score::double precision,
                'match_explanation', j.match_explanation,
                'status', j.status,
                'date_posted', j.date_posted,
                'created_at', j.created_at,
                'updated_at', j.updated_at,
                'application_url', j.application_url,
                'remote_type', coalesce(j.remote_type, 'unknown'),
                'employment_type', j.employment_type,
                'salary_min', j.salary_min::double precision,
                'salary_max', j.salary_max::double precision,
                'salary_currency', j.salary_currency,
                'salary_period', j.salary_period,
                'first_observed_at', j.first_observed_at,
                'last_observed_at', j.last_observed_at,
                'source_verification_status', j.source_verification_status,
                'discovery_metadata', coalesce(j.discovery_metadata::jsonb, '{}'::jsonb)
            ) AS job,
            CASE WHEN c.id IS NOT NULL THEN jsonb_build_object(
                'id', c.id,
                'name', c.name,
                'domain', c.domain,
                'metadata_', coalesce(c.metadata::jsonb, '{}'::jsonb)
            ) ELSE NULL END AS company
        FROM jobs j
        LEFT JOIN companies c ON c.id = j.company_id
        WHERE ($1::text IS NULL OR j.source_platform = $1 OR EXISTS (
                SELECT 1 FROM job_source_observations o WHERE o.job_id = j.id AND o.source = $1
            ))
            AND ($2::text IS NULL OR position($2 IN lower(j.title)) > 0)
            AND ($3::text IS NULL OR position($3 IN lower(coalesce(j.location, ''))) > 0)
            AND ($4::text IS NULL OR j.remote_type = $4)
            AND ($5::text IS NULL OR j.employment_type = $5)
            AND ($6::text IS NULL OR lower(coalesce(j.experience_level, '')) = $6)
            AND ($7::timestamptz IS NULL OR j.date_posted >= $7)
            AND ($8::timestamptz IS NULL OR j.last_observed_at >= $8)
        ORDER BY j.last_observed_at DESC NULLS LAST, j.id
        LIMIT 5001",
    )
    .bind(platform.as_deref())
    .bind(role_lower.as_deref())
    .bind(location_lower.as_deref())
    .bind(query.remote_type.as_deref())
    .bind(query.employment_type.as_deref())
    .bind(exp_lower.as_deref())
    .bind(published_after)
    .bind(observed_after)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;

    if rows.len() > 5000 {
        return Err(Failure("job_search_filter_limit"));
    }

    let job_ids: Vec<Uuid> = rows
        .iter()
        .filter_map(|(j, _)| j["id"].as_str().and_then(|s| s.parse::<Uuid>().ok()))
        .collect();
    let packet_rows: Vec<(Uuid, String, Option<String>)> = if job_ids.is_empty() {
        vec![]
    } else {
        sqlx::query_as(
            "SELECT job_id, lifecycle_state, tracking_state
             FROM application_packets WHERE job_id = ANY($1)
             ORDER BY job_id, id",
        )
        .bind(&job_ids)
        .fetch_all(&mut **tx)
        .await
        .map_err(db)?
    };
    let mut packets: HashMap<Uuid, Vec<Value>> = HashMap::new();
    for (jid, lifecycle, tracking) in packet_rows {
        packets
            .entry(jid)
            .or_default()
            .push(json!({"lifecycle_state": lifecycle, "tracking_state": tracking}));
    }

    let mut sizes: HashMap<Uuid, Value> = HashMap::new();
    if query.company_size_band.is_some() {
        let company_ids: Vec<Uuid> = rows
            .iter()
            .filter_map(|(_, c)| c.as_ref()?.get("id")?.as_str()?.parse::<Uuid>().ok())
            .collect();
        if !company_ids.is_empty() {
            let snapshots: Vec<(Uuid, Value)> = sqlx::query_as(
                "SELECT company_id, to_jsonb(o)
                 FROM company_source_observations o
                 WHERE company_id = ANY($1)
                 ORDER BY company_id, observed_at DESC, id
                 LIMIT 10001",
            )
            .bind(&company_ids)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
            if snapshots.len() > 10000 {
                return Err(Failure("job_search_filter_limit"));
            }
            let mut grouped: HashMap<Uuid, Vec<Value>> = HashMap::new();
            for (cid, obs) in snapshots {
                grouped.entry(cid).or_default().push(obs);
            }
            for (cid, obs) in grouped {
                sizes.insert(
                    cid,
                    crate::startup_catalog::intelligence::company_size(&obs, now, 180)?,
                );
            }
        }
    }

    let history = if parsed_profile.is_some() {
        crate::execution::reviewed_history::load_in(tx, now).await?
    } else {
        vec![]
    };

    let wanted_country = query.country.as_deref().map(|raw| {
        let lower = raw.to_lowercase();
        if matches!(lower.as_str(), "in" | "ind") {
            "india".into()
        } else {
            lower
        }
    });
    let wanted_skill = query.skill.as_deref().map(folded);

    let mut items = Vec::new();
    for (mut job, company) in rows {
        let fit = experience_fit(&job, approved_years);
        if query.approved_experience_fit && fit != "within_published_range" {
            continue;
        }
        if let Some(ref wanted) = wanted_country {
            let actual = job["discovery_metadata"]["country"]
                .as_str()
                .unwrap_or("")
                .to_lowercase();
            let actual = if matches!(actual.as_str(), "in" | "ind") {
                "india".into()
            } else {
                actual
            };
            if &actual != wanted {
                continue;
            }
        }
        if let Some(band) = query.company_size_band.as_deref() {
            let cid = company
                .as_ref()
                .and_then(|c| c["id"].as_str())
                .and_then(|s| s.parse::<Uuid>().ok());
            let size = cid.and_then(|id| sizes.get(&id));
            let Some(size) = size else {
                continue;
            };
            let (min_emp, max_emp, bands) = if band == "2-10" {
                (2, 10, json!(["1-10", "2-10"]))
            } else {
                (11, 50, json!(["11-50"]))
            };
            let size_filters = json!({
                "min_employees": min_emp,
                "max_employees": max_emp,
                "size_bands": bands,
                "include_unknown_size": false,
            });
            if !crate::startup_catalog::rules::size_allowed(size, &size_filters)? {
                continue;
            }
        }

        let jid = job["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_catalog_job_record"))?;
        let job_packets = packets.get(&jid).map(Vec::as_slice).unwrap_or(&[]);
        if !crate::startup_catalog::search::matches_status(
            &job,
            job_packets,
            &query.application_status,
        ) {
            continue;
        }
        if let Some(ref skill_folded) = wanted_skill {
            let has_skill = job["skills_required"].as_array().is_some_and(|arr| {
                arr.iter()
                    .any(|v| v.as_str().is_some_and(|s| folded(s) == *skill_folded))
            });
            if !has_skill {
                continue;
            }
        }

        let match_result = if let Some(ref profile) = parsed_profile {
            let listing: Listing = serde_json::from_value(job.clone())
                .map_err(|_| Failure("invalid_catalog_job_record"))?;
            let company_struct = company.as_ref().map(|c| Company {
                name: c["name"].as_str().unwrap_or("").into(),
                domain: c["domain"].as_str().map(str::to_owned),
                startup_stage: c["metadata_"]["startup_discovery"]["stage"]
                    .as_str()
                    .map(str::to_owned),
                startup_source: c["metadata_"]["startup_discovery"]["source"]
                    .as_str()
                    .map(str::to_owned),
            });
            let prior = crate::execution::reviewed_history::previously_applied(
                &job,
                company.as_ref(),
                &history,
            );
            let m = discovery_match(&listing, profile, company_struct.as_ref(), prior);
            if query.exclude_preferences && !m.exclusion_reasons.is_empty() {
                continue;
            }
            if query
                .minimum_match_score
                .is_some_and(|min| m.match_score < min)
            {
                continue;
            }
            Some(serde_json::to_value(m).map_err(|_| Failure("invalid_match_result"))?)
        } else {
            None
        };

        let meta = job["discovery_metadata"].clone();
        if let Some(obj) = job.as_object_mut() {
            obj.remove("discovery_metadata");
            for key in [
                "created_at",
                "updated_at",
                "date_posted",
                "first_observed_at",
                "last_observed_at",
            ] {
                if let Some(val) = obj.get(key).cloned() {
                    obj.insert(key.into(), format_ts(val)?);
                }
            }
            obj.insert(
                "company_name".into(),
                company
                    .as_ref()
                    .map(|c| c["name"].clone())
                    .unwrap_or(Value::Null),
            );
            obj.insert(
                "company_domain".into(),
                company
                    .as_ref()
                    .map(|c| c["domain"].clone())
                    .unwrap_or(Value::Null),
            );
            obj.insert(
                "application_state".into(),
                job_packets
                    .first()
                    .map(|p| p["lifecycle_state"].clone())
                    .unwrap_or(Value::Null),
            );
            obj.insert(
                "experience_fit".into(),
                json!(if query.approved_experience_fit {
                    fit
                } else {
                    "unknown"
                }),
            );
            obj.insert(
                "company_intelligence".into(),
                company
                    .as_ref()
                    .and_then(|c| c["metadata_"].get("startup_discovery"))
                    .cloned()
                    .unwrap_or_else(|| json!({})),
            );
            obj.insert(
                "country".into(),
                meta.get("country").cloned().unwrap_or(Value::Null),
            );
            obj.insert(
                "region".into(),
                meta.get("region").cloned().unwrap_or(Value::Null),
            );
            obj.insert(
                "skills_preferred".into(),
                meta.get("skills_preferred")
                    .filter(|v| v.is_array())
                    .cloned()
                    .unwrap_or_else(|| json!([])),
            );
            obj.insert(
                "equity".into(),
                meta.get("equity").cloned().unwrap_or(Value::Null),
            );
            obj.insert(
                "quality_flags".into(),
                meta.get("quality_flags")
                    .filter(|v| v.is_array())
                    .cloned()
                    .unwrap_or_else(|| json!([])),
            );
            obj.insert("match".into(), match_result.unwrap_or(Value::Null));
            obj.insert("source_observations".into(), json!([]));
        }
        items.push(job);
    }

    if query.sort == "match" {
        items.sort_by(|a, b| {
            let sa = a["match"]["match_score"].as_f64().unwrap_or(0.0);
            let sb = b["match"]["match_score"].as_f64().unwrap_or(0.0);
            sb.total_cmp(&sa)
        });
    } else if query.sort == "oldest" {
        items.reverse();
    }

    let total = items.len();
    let offset = ((query.page - 1) * query.limit) as usize;
    let mut selected: Vec<Value> = items
        .into_iter()
        .skip(offset)
        .take(query.limit as usize)
        .collect();

    let selected_ids: Vec<Uuid> = selected
        .iter()
        .filter_map(|j| j["id"].as_str().and_then(|s| s.parse::<Uuid>().ok()))
        .collect();
    if !selected_ids.is_empty() {
        let obs_rows: Vec<(Uuid, Value)> = sqlx::query_as(
            "WITH ranked AS (
                SELECT job_id,
                    jsonb_build_object(
                        'source', source,
                        'source_job_id', source_job_id,
                        'original_url', original_url,
                        'first_observed_at', first_observed_at,
                        'last_observed_at', last_observed_at,
                        'provenance', provenance,
                        'verification_status', verification_status
                    ) AS obs,
                    row_number() OVER (PARTITION BY job_id ORDER BY last_observed_at DESC, id) AS pos
                FROM job_source_observations
                WHERE job_id = ANY($1)
            )
            SELECT job_id, obs FROM ranked WHERE pos <= 20 ORDER BY job_id, pos",
        )
        .bind(&selected_ids)
        .fetch_all(&mut **tx)
        .await
        .map_err(db)?;
        let mut by_job: HashMap<String, Vec<Value>> = HashMap::new();
        for (jid, obs) in obs_rows {
            by_job.entry(jid.to_string()).or_default().push(obs);
        }
        for item in &mut selected {
            if let Some(id) = item["id"].as_str().map(str::to_owned)
                && let Some(obs) = by_job.remove(&id)
            {
                item["source_observations"] = Value::Array(obs);
            }
        }
    }

    Ok(json!({
        "total": total,
        "page": query.page,
        "limit": query.limit,
        "jobs": selected,
    }))
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn route_distinguishes_jobs_search_from_uuid_detail() {
        assert!(matches!(route("/api/v1/jobs/search"), Some(Route::Search)));
        assert!(matches!(
            route("/api/v1/jobs/not-a-uuid"),
            Some(Route::Detail("not-a-uuid"))
        ));
    }

    #[test]
    fn search_query_parses_dashboard_defaults_and_rejects_invalid_enums() {
        let parsed = SearchQuery::parse(Some(
            "role=backend&application_status=not_applied&sort=match&minimum_match_score=50&exclude_preferences=false&page=2&limit=20",
        ))
        .expect("valid query");
        assert_eq!(parsed.role.as_deref(), Some("backend"));
        assert_eq!(parsed.application_status, "not_applied");
        assert_eq!(parsed.sort, "match");
        assert_eq!(parsed.minimum_match_score, Some(50.0));
        assert!(!parsed.exclude_preferences);
        assert_eq!(parsed.page, 2);
        assert_eq!(parsed.limit, 20);

        assert_eq!(
            SearchQuery::parse(Some("sort=random")).err(),
            Some(Failure("invalid_job_search"))
        );
        assert_eq!(
            SearchQuery::parse(Some("minimum_match_score=105")).err(),
            Some(Failure("invalid_job_search"))
        );
    }
}
