//! Read-only access to retained discovery schedules and their historical results.
use super::db;
use crate::{Failure, Result, configuration::Configuration};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

const INVALID: Failure = Failure("invalid_saved_discovery_automation");
const BAD_REQUEST: Failure = Failure("invalid_dashboard_request");

#[derive(Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
struct Schedule {
    enabled: bool,
    sources: Vec<String>,
    interval_seconds: i64,
    limit: i64,
    approved_profile_id: Option<Uuid>,
    approved_profile_version: Option<i32>,
}

impl Default for Schedule {
    fn default() -> Self {
        Self {
            enabled: false,
            sources: vec![],
            interval_seconds: 21_600,
            limit: 20,
            approved_profile_id: None,
            approved_profile_version: None,
        }
    }
}

struct Saved {
    version: i32,
    configuration: Schedule,
    next_run_at: Option<DateTime<Utc>>,
    last_run_at: Option<DateTime<Utc>>,
    heartbeat_at: Option<DateTime<Utc>>,
}

type Row = (
    i32,
    bool,
    Option<Value>,
    Option<DateTime<Utc>>,
    Option<DateTime<Utc>>,
    Option<DateTime<Utc>>,
);

async fn schedule(tx: &mut Transaction<'_, Postgres>) -> Result<Saved> {
    let row = sqlx::query_as::<_, Row>(
        "SELECT version,enabled,CASE WHEN octet_length(configuration::text)<=8192
             THEN configuration END AS configuration,next_run_at,last_run_at,heartbeat_at
         FROM automation_schedule WHERE key='primary'",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let Some((version, enabled, saved_configuration, next_run_at, last_run_at, heartbeat_at)) = row
    else {
        return Ok(Saved {
            version: 1,
            configuration: Schedule::default(),
            next_run_at: None,
            last_run_at: None,
            heartbeat_at: None,
        });
    };
    let mut values = saved_configuration.ok_or(INVALID)?;
    values
        .as_object_mut()
        .ok_or(INVALID)?
        .insert("enabled".into(), json!(enabled));
    let configuration: Schedule = serde_json::from_value(values).map_err(|_| INVALID)?;
    let sources = &configuration.sources;
    if version < 1
        || !(300..=604_800).contains(&configuration.interval_seconds)
        || !(1..=50).contains(&configuration.limit)
        || sources.iter().collect::<BTreeSet<_>>().len() != sources.len()
        || sources.iter().any(|source| match source.as_str() {
            "hacker_news" | "arbeitnow" | "greenhouse" => false,
            "remotive" => configuration.interval_seconds < 21_600,
            _ => true,
        })
        || (enabled && sources.is_empty())
        || configuration.approved_profile_id.is_some()
            != configuration.approved_profile_version.is_some()
        || configuration
            .approved_profile_version
            .is_some_and(|version| version < 1)
    {
        return Err(INVALID);
    }
    Ok(Saved {
        version,
        configuration,
        next_run_at,
        last_run_at,
        heartbeat_at,
    })
}

async fn profile(tx: &mut Transaction<'_, Postgres>) -> Result<Option<(Uuid, i32)>> {
    sqlx::query_as("SELECT id,version FROM candidate_profiles WHERE singleton_key='primary'")
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}

fn approved(candidate: Option<(Uuid, i32)>, config: &Schedule) -> bool {
    candidate.is_some_and(|(id, version)| {
        config.approved_profile_id == Some(id) && config.approved_profile_version == Some(version)
    })
}

pub(super) async fn status(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let saved = schedule(tx).await?;
    let candidate = profile(tx).await?;
    let settings = saved.configuration;
    let mut blockers = vec!["legacy_worker_inactive".to_owned()];
    if !config.legacy_discovery_enabled {
        blockers.push("operational_activation_required".into());
    }
    if settings.sources.is_empty() {
        blockers.push("sources_required".into());
    }
    for source in &settings.sources {
        if config.sources.job(source, now)?["availability"] != "available" {
            blockers.push(format!("{source}_configuration_required"));
        }
    }
    let active: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM automation_executions WHERE state IN ('claimed','running')",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    Ok(json!({
        "state":if settings.enabled {"awaiting_configuration"}else{"disabled"},
        "version":saved.version,"configuration":settings,"blockers":blockers,
        "next_run_at":saved.next_run_at,"last_run_at":saved.last_run_at,
        "heartbeat_at":saved.heartbeat_at,"worker_ready":false,"active_executions":active,
        "profile":candidate.map(|(id,version)|json!({"id":id,"version":version})),
        "matching":if approved(candidate, &settings) {"approved"}else{"awaiting_profile_approval"},
    }))
}

fn history_filter(query: Option<&str>) -> Result<(Option<String>, i64, i64)> {
    let query = query.unwrap_or("");
    if query.len() > 512 {
        return Err(BAD_REQUEST);
    }
    let mut params = BTreeMap::new();
    let url =
        reqwest::Url::parse(&format!("http://127.0.0.1/?{query}")).map_err(|_| BAD_REQUEST)?;
    for (key, value) in url.query_pairs() {
        if !matches!(key.as_ref(), "state" | "limit" | "offset")
            || params
                .insert(key.into_owned(), value.into_owned())
                .is_some()
        {
            return Err(BAD_REQUEST);
        }
    }
    let state = params.remove("state");
    if state.as_deref().is_some_and(|state| {
        !matches!(
            state,
            "pending" | "claimed" | "running" | "completed" | "partial" | "failed" | "blocked"
        )
    }) {
        return Err(BAD_REQUEST);
    }
    let number = |key, default, min, max| {
        params.get(key).map_or(Ok(default), |value| {
            value
                .parse::<i64>()
                .ok()
                .filter(|n| (min..=max).contains(n))
                .ok_or(BAD_REQUEST)
        })
    };
    Ok((
        state,
        number("limit", 30, 1, 100)?,
        number("offset", 0, 0, 100_000)?,
    ))
}

pub(super) async fn history(
    tx: &mut Transaction<'_, Postgres>,
    query: Option<&str>,
) -> Result<Value> {
    let (state, limit, offset) = history_filter(query)?;
    let rows: Vec<Option<Value>> = sqlx::query_scalar(
        "SELECT CASE WHEN octet_length(outcome::text)<=32768 THEN jsonb_build_object(
            'id',id,'source',source,'trigger_type',trigger_type,'state',state,
            'created_at',created_at,'started_at',started_at,'finished_at',finished_at,
            'diagnostic',diagnostic,'outcome',outcome,'discovery_run_id',discovery_run_id,
            'attempts',attempts,'available_at',available_at,'lease_until',lease_until)
         END FROM automation_executions
         WHERE ($1::text IS NULL OR state=$1)
         ORDER BY created_at DESC,id LIMIT $2 OFFSET $3",
    )
    .bind(state)
    .bind(limit)
    .bind(offset)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    Ok(
        json!({"executions":rows.into_iter().map(|row|row.ok_or(INVALID)).collect::<Result<Vec<_>>>()?}),
    )
}

pub(super) async fn matches(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let saved = schedule(tx).await?;
    let candidate = profile(tx).await?;
    let Some((id, version)) = candidate.filter(|_| approved(candidate, &saved.configuration))
    else {
        return Ok(json!({"matches":[]}));
    };
    let rows: Vec<(Uuid, DateTime<Utc>, Option<Value>)> = sqlx::query_as(
        "SELECT job_id,scored_at,CASE WHEN octet_length(result::text)<=32768 THEN result END
         FROM automation_matches WHERE profile_id=$1 AND profile_version=$2
         ORDER BY scored_at DESC,job_id LIMIT 100",
    )
    .bind(id)
    .bind(version)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let mut scored_jobs = Vec::with_capacity(rows.len());
    for (job, scored_at, row) in rows {
        let mut result = row.ok_or(INVALID)?;
        let score = result["match_score"]
            .as_f64()
            .filter(|n| (0.0..=100.0).contains(n))
            .ok_or(INVALID)?;
        let fields = result.as_object_mut().ok_or(INVALID)?;
        fields.extend([
            ("job_id".into(), json!(job)),
            ("profile_version".into(), json!(version)),
            ("scored_at".into(), json!(scored_at)),
        ]);
        scored_jobs.push((job, score, result));
    }
    scored_jobs.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    Ok(json!({"matches":scored_jobs.into_iter().map(|(_,_,item)|item).collect::<Vec<_>>()}))
}
