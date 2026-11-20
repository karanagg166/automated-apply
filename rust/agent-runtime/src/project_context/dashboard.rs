//! Owner dashboard routes over the existing candidate-context preference records.
mod approval;

use super::{CONFIGURATION_KEY, Snapshot, configuration_record, invalid, key};
use crate::{
    Failure, Result,
    context_contract::{Kind, normalize},
    execution,
    python_json::digest,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};

const PREFIX: &str = "/api/v1/dashboard/candidate-context/";

#[derive(Clone, Copy)]
pub(crate) enum Route<'a> {
    Configuration,
    Projects,
    Project(&'a str),
    Approve(&'a str),
    Answer,
}

impl Route<'_> {
    pub(crate) fn allows(self, method: &str) -> bool {
        method == "GET" && !matches!(self, Self::Approve(_))
            || method == "PUT" && matches!(self, Self::Configuration)
            || method == "POST" && matches!(self, Self::Approve(_))
    }

    pub(crate) fn allow(self) -> &'static str {
        match self {
            Self::Configuration => "GET, PUT",
            Self::Approve(_) => "POST",
            _ => "GET",
        }
    }
}

pub(crate) fn route(path: &str) -> Option<Route<'_>> {
    match path.strip_prefix(PREFIX)? {
        "configuration" => Some(Route::Configuration),
        "projects" => Some(Route::Projects),
        "answer" => Some(Route::Answer),
        tail => {
            let project = tail.strip_prefix("projects/")?;
            let (id, action) = project.split_once('/').unwrap_or((project, ""));
            let suffix = id.strip_prefix("project-")?;
            let alphanumeric = |b: u8| b.is_ascii_lowercase() || b.is_ascii_digit();
            if suffix.len() > 31
                || !suffix.bytes().next().is_some_and(alphanumeric)
                || !suffix.bytes().all(|b| alphanumeric(b) || b == b'-')
            {
                return None;
            }
            match action {
                "" if project == id => Some(Route::Project(id)),
                "approve" => Some(Route::Approve(id)),
                _ => None,
            }
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigurationUpdate {
    expected_revision: u64,
    configuration: Value,
}

struct AnswerQuery {
    question: String,
    project_rank: Option<usize>,
    max_words: usize,
    max_characters: usize,
}

impl AnswerQuery {
    fn parse(query: Option<&str>) -> Result<Self> {
        let invalid = Failure("invalid_project_context_answer_query");
        let query = query
            .filter(|q| q.len() <= 26_000 && !q.contains('#'))
            .ok_or(invalid)?;
        let url =
            reqwest::Url::parse(&format!("http://127.0.0.1/?{query}")).map_err(|_| invalid)?;
        let mut pairs = std::collections::HashMap::new();
        for (name, value) in url.query_pairs() {
            if !matches!(
                name.as_ref(),
                "question" | "project_rank" | "max_words" | "max_characters"
            ) || pairs.insert(name, value).is_some()
            {
                return Err(invalid);
            }
        }
        let number = |name, bounds: std::ops::RangeInclusive<usize>| {
            pairs
                .get(name)
                .map(|value| {
                    value
                        .parse::<usize>()
                        .ok()
                        .filter(|n| bounds.contains(n))
                        .ok_or(invalid)
                })
                .transpose()
        };
        let question = pairs
            .get("question")
            .filter(|text| (1..=2000).contains(&text.chars().count()))
            .ok_or(invalid)?
            .to_string();
        Ok(Self {
            question,
            project_rank: number("project_rank", 1..=30)?,
            max_words: number("max_words", 10..=500)?.unwrap_or(100),
            max_characters: number("max_characters", 50..=8000)?.unwrap_or(2000),
        })
    }
}

fn db(_: sqlx::Error) -> Failure {
    Failure("dashboard_database_error")
}

fn stored_error(error: Failure) -> Failure {
    match error.0 {
        "invalid_project_context_record" | "project_context_limit" => {
            Failure("invalid_saved_project_context")
        }
        _ => error,
    }
}

fn next_revision(record: &Value) -> Result<i64> {
    record["revision"]
        .as_i64()
        .and_then(|n| n.checked_add(1))
        .ok_or_else(invalid)
}

async fn timestamp(tx: &mut Transaction<'_, Postgres>) -> Result<String> {
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    Ok(now.to_rfc3339_opts(SecondsFormat::Micros, false))
}

async fn lock_record(tx: &mut Transaction<'_, Postgres>, name: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE")
        .bind(name)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}

async fn save(
    tx: &mut Transaction<'_, Postgres>,
    name: &str,
    old: Option<&Value>,
    new: &Value,
) -> Result<()> {
    let affected = match old {
        Some(old) => sqlx::query("UPDATE owner_preferences SET value=$2, updated_at=clock_timestamp() WHERE key=$1 AND value=$3")
            .bind(name).bind(new).bind(old).execute(&mut **tx).await.map_err(db)?,
        None => sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES ($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT (key) DO NOTHING")
            .bind(name).bind(new).execute(&mut **tx).await.map_err(db)?,
    }.rows_affected();
    if affected != 1 {
        return Err(Failure("concurrent_record_change_reload"));
    }
    Ok(())
}

async fn update_configuration(
    tx: &mut Transaction<'_, Postgres>,
    input: ConfigurationUpdate,
) -> Result<Value> {
    let proposed = normalize(
        Kind::Configuration,
        json!({"configuration": input.configuration}),
    )
    .map_err(|_| Failure("invalid_project_context_request"))?;
    let after = &proposed["configuration"];
    if after["resume"]["auto_sync_enabled"] == true {
        return Err(Failure("drive_oauth_deferred_use_manual_pdf_upload"));
    }
    let stored = lock_record(tx, CONFIGURATION_KEY).await?;
    let mut previous = configuration_record(stored.clone())?;
    if previous["revision"].as_u64() != Some(input.expected_revision) {
        return Err(Failure("configuration_changed_reload"));
    }
    let before = &previous["configuration"];
    let changed: Vec<_> = ["links", "projects", "resume"]
        .into_iter()
        .filter(|field| before[*field] != after[*field])
        .collect();
    if changed.is_empty() {
        return Ok(previous);
    }
    let revision = next_revision(&previous)?;
    let event = json!({"previous_hash":digest(before),"current_hash":digest(after),"changed_fields":changed,
                       "source":"owner_dashboard","actor_ref":"owner","created_at":timestamp(tx).await?});
    let audits = previous["audits"].as_array_mut().ok_or_else(invalid)?;
    if audits.len() >= 100 {
        return Err(Failure("configuration_audit_archive_required"));
    }
    audits.push(event);
    previous["revision"] = json!(revision);
    previous["configuration"] = after.clone();
    save(tx, CONFIGURATION_KEY, stored.as_ref(), &previous).await?;
    Ok(previous)
}

async fn read(
    connection: &mut PgConnection,
    route: Route<'_>,
    query: Option<&str>,
) -> Result<Value> {
    if matches!(route, Route::Configuration) {
        let saved = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(CONFIGURATION_KEY)
            .fetch_optional(connection)
            .await
            .map_err(db)?;
        return configuration_record(saved);
    }
    if let Route::Project(id) = route {
        let mut tx = connection.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let saved = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(CONFIGURATION_KEY)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
        let configuration = configuration_record(saved)?;
        let record = configuration["configuration"]["projects"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .find(|project| project["id"] == id)
            .map(key)
            .transpose()?
            .unwrap_or_else(|| format!("candidate_{id}"));
        let knowledge: Option<Value> =
            sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(record)
                .fetch_optional(&mut *tx)
                .await
                .map_err(db)?;
        let knowledge = normalize(
            Kind::Knowledge,
            knowledge.filter(super::truth).unwrap_or(json!({})),
        )?;
        tx.commit().await.map_err(db)?;
        return Ok(knowledge);
    }
    let answer = match route {
        Route::Answer => Some(AnswerQuery::parse(query)?),
        _ => None,
    };
    let snapshot = Snapshot::load(connection).await?;
    match route {
        Route::Projects => Ok(Value::Array(snapshot.knowledge.into_iter().map(|(project, record)| {
            let candidate = &record["candidate"];
            let approved = &record["approved"];
            json!({"project":project,"revision":record["revision"],"candidate_revision":candidate["revision"],
                   "approved_revision":approved["revision"],"last_checked_commit":record["last_checked_commit"],
                   "built_at":record["built_at"],"fact_count":candidate["facts"].as_array().map_or(0, Vec::len),
                   "approved_fact_count":approved["facts"].as_array().map_or(0, Vec::len)})
        }).collect())),
        Route::Answer => {
            let input = answer.ok_or_else(invalid)?;
            snapshot.conversation_answer(&input.question, input.project_rank, input.max_words, input.max_characters)
        }
        _ => Err(invalid()),
    }
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    if query.is_some() && !matches!(route, Route::Answer) || (method == "GET" && !body.is_empty()) {
        return Err(Failure("invalid_project_context_request"));
    }
    if method == "GET" {
        return read(connection, route, query).await.map_err(stored_error);
    }
    enum Mutation<'a> {
        Update(ConfigurationUpdate),
        Approve(&'a str, approval::Input),
    }
    let mutation = match route {
        Route::Configuration => {
            let input = serde_json::from_slice(body)
                .map_err(|_| Failure("invalid_project_context_request"))?;
            Mutation::Update(input)
        }
        Route::Approve(id) => Mutation::Approve(id, approval::Input::parse(body)?),
        _ => return Err(invalid()),
    };
    let mut tx = connection.begin().await.map_err(db)?;
    let result = async {
        execution::lock_owner_in(&mut tx).await?;
        match mutation {
            Mutation::Update(input) => update_configuration(&mut tx, input).await,
            Mutation::Approve(id, input) => approval::approve(&mut tx, id, input).await,
        }
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("dashboard_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback().await.map_err(db)?;
            Err(stored_error(error))
        }
    }
}
