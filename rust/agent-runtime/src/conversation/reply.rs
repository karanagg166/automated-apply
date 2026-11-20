//! Compose owner turns over saved state and existing packet preparation.
use super::{
    intent::{self, Intent},
    jobs, memory,
};
use crate::{Failure, Result, configuration::Configuration};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::sync::LazyLock;
use uuid::Uuid;

fn db(_: sqlx::Error) -> Failure {
    Failure("conversation_operation_database_error")
}

const HELP: &str = "Try “Find Rust jobs in India”, “Compare jobs”, “Check resume status”, or “Show skills”. Search uses saved jobs. Application preparation opens a packet for dashboard review.";

fn message(status: &str, reply: &str) -> Value {
    json!({"status":status,"reply":reply,"submitted":false})
}

fn clean(value: &Value) -> String {
    static SECRETS: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"(?:sbp_|sk-)[A-Za-z0-9_-]+|\d{6,}:[A-Za-z0-9_-]{20,}").unwrap()
    });
    let text: String = value
        .as_str()
        .unwrap_or_default()
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    SECRETS
        .replace_all(&text, "[redacted]")
        .chars()
        .take(120)
        .collect()
}

fn selected_ids(loaded: &memory::Loaded) -> Result<Vec<Uuid>> {
    loaded.value()["job_ids"]
        .as_array()
        .ok_or(Failure("conversation_memory_review_required"))?
        .iter()
        .map(|id| {
            id.as_str()
                .and_then(|s| s.parse().ok())
                .ok_or(Failure("conversation_memory_review_required"))
        })
        .collect()
}

async fn profile(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let Some(profile) = crate::knowledge::reviewed_profile(tx).await? else {
        return Ok(message(
            "profile_review_required",
            "Review your current profile in the dashboard.",
        ));
    };
    let skills = profile
        .facts
        .verified_skills
        .iter()
        .take(20)
        .map(|name| clean(&json!(name)))
        .collect::<Vec<_>>()
        .join(", ");
    let roles = profile
        .facts
        .preferences
        .target_titles
        .iter()
        .take(10)
        .map(|name| clean(&json!(name)))
        .collect::<Vec<_>>()
        .join(", ");
    Ok(message(
        "profile_query",
        &format!(
            "Reviewed profile version {}. Skills: {}. Preferred roles: {}.",
            profile.pin.version,
            if skills.is_empty() {
                "Not specified"
            } else {
                &skills
            },
            if roles.is_empty() {
                "Not specified"
            } else {
                &roles
            },
        ),
    ))
}

async fn project(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut memory::Loaded,
    intent: &Intent,
) -> Result<Value> {
    let mut current = loaded.value().clone();
    let rank = intent
        .project_rank
        .map(usize::from)
        .or_else(|| current["project_rank"].as_u64().map(|rank| rank as usize));
    current["project_rank"] = json!(rank);
    let question = if intent.follow_up.as_deref() == Some("answer") {
        current["answer_question"]
            .as_str()
            .or(intent.subject.as_deref())
    } else {
        current["answer_question"] = json!(intent.subject);
        intent.subject.as_deref()
    }
    .unwrap_or("Describe my best project");
    let snapshot = crate::project_context::Snapshot::load_in(tx).await?;
    let answer = snapshot.conversation_answer(
        question,
        rank,
        usize::from(intent.max_words),
        usize::from(intent.max_characters),
    )?;
    memory::save_in(tx, loaded, current).await?;
    if answer["status"] != "draft_requires_review" {
        return Ok(message(
            "missing_approved_context",
            "No matching approved project evidence is available. Review your projects in the dashboard.",
        ));
    }
    let draft = answer["text"]
        .as_str()
        .ok_or(Failure("invalid_project_context_record"))?;
    Ok(message(
        "approved_context_draft",
        &format!("Draft for review\n{draft}"),
    ))
}

async fn resume(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let row: Option<(String, bool, bool)> = sqlx::query_as(
        "SELECT status, active_version_id IS NOT NULL, sync_enabled FROM resume_drive_sources WHERE key = 'primary'",
    ).fetch_optional(&mut **tx).await.map_err(db)?;
    let Some((status, approved, enabled)) = row else {
        return Ok(message(
            "resume_not_configured",
            "Review your canonical PDF in the dashboard. Resume sync has no saved source.",
        ));
    };
    Ok(message(
        "resume_status",
        &format!(
            "Resume sync: {}. Approved version: {}. Periodic checking: {}.",
            clean(&json!(status)),
            if approved {
                "available"
            } else {
                "not selected"
            },
            if enabled { "enabled" } else { "disabled" },
        ),
    ))
}

async fn tracking(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let rows: Vec<(String, i64)> = sqlx::query_as(
        "SELECT tracking_state, count(*) FROM application_packets GROUP BY tracking_state ORDER BY tracking_state LIMIT 50",
    ).fetch_all(&mut **tx).await.map_err(db)?;
    let counts = rows
        .iter()
        .map(|(state, count)| format!("{}: {count}", clean(&json!(state))))
        .collect::<Vec<_>>()
        .join(", ");
    Ok(message(
        "application_status",
        &format!(
            "Saved application packet counts: {}.",
            if counts.is_empty() { "0" } else { &counts }
        ),
    ))
}

async fn connections(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    intent: &Intent,
    now: DateTime<Utc>,
) -> Result<Value> {
    let report = crate::telegram_local::connections_in(tx, config, now).await?;
    let target = intent.connection.as_deref().map(|target| match target {
        "yc" => "work at a startup",
        "chrome" => "selected browser",
        "supabase" => "postgresql",
        other => other,
    });
    let lines = report["connections"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| {
            let name = clean(&row["name"]);
            target
                .is_none_or(|target| folded(&name).contains(target))
                .then(|| format!("{name}: {}", clean(&row["state"])))
        })
        .collect::<Vec<_>>();
    let text = if lines.is_empty() {
        "No saved status is available for that connection.".to_owned()
    } else {
        lines.join("\n")
    };
    Ok(message("connection_status", &text))
}

async fn search(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut memory::Loaded,
    mut intent: Intent,
    prepare: bool,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let found = jobs::search(tx, &mut intent, None, prepare, now).await?;
    if let Some(names) = found.clarification {
        let names = names
            .iter()
            .map(|n| clean(&json!(n)))
            .collect::<Vec<_>>()
            .join(", ");
        return Ok(message(
            "clarification_required",
            &format!("Which company did you mean? {names}"),
        ));
    }
    let ids: Vec<_> = found.jobs.iter().map(|job| job.id).collect();
    let mut state = loaded.value().clone();
    state["job_ids"] = json!(ids);
    state["intent"] =
        serde_json::to_value(&intent).map_err(|_| Failure("invalid_conversation_intent"))?;
    state["prepare"] = json!(prepare);
    state["current_company"] = json!(intent.company);
    state["selected_job_id"] = if prepare && ids.len() == 1 {
        json!(ids[0])
    } else {
        Value::Null
    };
    memory::save_in(tx, loaded, state).await?;
    if found.jobs.is_empty() {
        return Ok(message(
            "no_matches",
            "No matching saved jobs were found in the search window.",
        ));
    }
    if prepare && found.jobs.len() == 1 {
        return jobs::prepare(tx, &found.jobs[0], config, now).await;
    }
    let mut lines = Vec::new();
    let mut displayed = Vec::new();
    let mut units: usize = 0;
    for (i, job) in found.jobs.iter().enumerate() {
        let title = clean(&job.data["title"]);
        let source = clean(&job.data["source_platform"]);
        let line = format!("{}. {title} · {source}\n{}", i + 1, job.public_url);
        units += line.encode_utf16().count() + 1;
        if units > 2950 {
            break;
        }
        lines.push(line);
        displayed.push(job.id);
    }
    if displayed != ids {
        let mut state = loaded.value().clone();
        state["job_ids"] = json!(displayed);
        memory::save_in(tx, loaded, state).await?;
    }
    let window = if found.limited {
        "\nThe search covered the latest 200 saved jobs."
    } else {
        ""
    };
    Ok(message(
        "selection_required",
        &format!(
            "Matching saved jobs\n{}\nReply with a listed number within 10 minutes. Review current availability in the dashboard.{window}",
            lines.join("\n")
        ),
    ))
}

async fn follow(
    tx: &mut Transaction<'_, Postgres>,
    loaded: &mut memory::Loaded,
    request: &Intent,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let ids = selected_ids(loaded)?;
    if request.follow_up.as_deref() == Some("clarify") {
        return Ok(message(
            "clarification_required",
            "Choose one request first: search, status, profile, resume, or connections.",
        ));
    }
    if ids.is_empty() || loaded.value()["intent"].is_null() {
        return Ok(message(
            "selection_required",
            "Search for saved jobs first, then choose a listed number or add a filter.",
        ));
    }
    let mut prior = intent::normalize(loaded.value()["intent"].clone())?;
    let prepare =
        loaded.value()["prepare"] == true || request.follow_up.as_deref() == Some("prepare");
    if request.follow_up.as_deref() == Some("filter") {
        if request.location.is_none() && request.days.is_none() && !request.remote {
            return Ok(message(
                "clarification_required",
                "Specify a location, remote jobs, or today's jobs.",
            ));
        }
        prior.category = "FILTER_JOBS".into();
        prior.location = request.location.clone().or(prior.location);
        prior.days = request.days.or(prior.days);
        prior.remote |= request.remote;
        return search(tx, loaded, prior, prepare, config, now).await;
    }
    let selected = match (request.job_id, request.selection) {
        (Some(id), _) => Some(id),
        (_, Some(number)) => number
            .checked_sub(1)
            .and_then(|i| ids.get(usize::from(i)).copied()),
        (None, None) => loaded.value()["selected_job_id"]
            .as_str()
            .and_then(|id| id.parse().ok()),
    };
    let wanted = if request.category == "JOB_COMPARISON" {
        ids
    } else if let Some(id) = selected.filter(|id| ids.contains(id)) {
        vec![id]
    } else {
        return Ok(message(
            "selection_required",
            "Choose an available number from your saved search.",
        ));
    };
    let mut current = jobs::search(tx, &mut prior, Some(&wanted), prepare, now)
        .await?
        .jobs;
    if current.is_empty() {
        return Ok(message(
            "selection_required",
            "That selection no longer matches your filters or saved history. Search again.",
        ));
    }
    if request.category == "JOB_COMPARISON" {
        current.sort_by(|a, b| {
            b.data["match_score"]
                .as_f64()
                .unwrap_or(-1.0)
                .total_cmp(&a.data["match_score"].as_f64().unwrap_or(-1.0))
                .then(a.id.cmp(&b.id))
        });
        let lines = current
            .iter()
            .take(5)
            .map(|job| {
                format!(
                    "{}: {}",
                    clean(&job.data["title"]),
                    job.data["match_score"]
                        .as_f64()
                        .map(|n| n.to_string())
                        .unwrap_or_else(|| "not scored".to_owned())
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        return Ok(message(
            "job_comparison",
            &format!("Saved match scores\n{lines}"),
        ));
    }
    let job = &current[0];
    let mut state = loaded.value().clone();
    state["selected_job_id"] = json!(job.id);
    state["prepare"] = json!(prepare);
    memory::save_in(tx, loaded, state).await?;
    if prepare {
        return jobs::prepare(tx, job, config, now).await;
    }
    Ok(message(
        "job_details",
        &format!(
            "{} · {}\n{}\nSaved status: {}.",
            clean(&job.data["title"]),
            clean(&job.data["source_platform"]),
            job.public_url,
            clean(&job.data["status"])
        ),
    ))
}

pub(crate) async fn respond(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    scope: memory::Scope,
    intent: Intent,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut loaded = memory::load_scope_in(tx, scope).await?;
    if intent.category == "RESET_CONTEXT" {
        memory::reset_in(tx, &mut loaded).await?;
        return Ok(message(
            "context_reset",
            "Previous job and project selection cleared.",
        ));
    }
    memory::record_in(tx, &mut loaded, &intent).await?;
    match intent.category.as_str() {
        "HELP" | "UNKNOWN" | "GENERAL_CHAT" => Ok(message("help", HELP)),
        "APPROVAL_REQUEST" => Ok(message(
            "owner_review_required",
            "Open the exact item in the dashboard to review it.",
        )),
        "PROFILE_QUERY" => profile(tx).await,
        "PROJECT_QUERY" | "ANSWER_PREPARATION" => project(tx, &mut loaded, &intent).await,
        "RESUME_STATUS" => resume(tx).await,
        "CONNECTION_STATUS" => connections(tx, config, &intent, now).await,
        "APPLICATION_STATUS" => tracking(tx).await,
        "GMAIL_DRAFT_PREVIEW" | "FOUNDER_RESEARCH_PREVIEW" => Ok(message(
            "manual_review_required",
            "Open the dashboard to review saved evidence and draft options.",
        )),
        "SHOW_JOB" | "JOB_COMPARISON" | "FOLLOW_UP" => {
            follow(tx, &mut loaded, &intent, config, now).await
        }
        "PREPARE_APPLICATION" if intent.url.is_some() => {
            let url = intent
                .url
                .as_deref()
                .ok_or(Failure("invalid_conversation_intent"))?;
            if !jobs::preview_allowed(jobs::policy(tx).await?.as_ref(), url)? {
                return Ok(message(
                    "denied",
                    "The application destination is disabled in your saved policy.",
                ));
            }
            let platform = crate::browser_profiles::commands::page_kind(url)?;
            Ok(message(
                "url_preview",
                &format!(
                    "Saved URL preview for {platform}. Open the dashboard to review the destination."
                ),
            ))
        }
        "FIND_JOBS" | "FILTER_JOBS" | "PREPARE_APPLICATION" => {
            let prepare = intent.category == "PREPARE_APPLICATION";
            search(tx, &mut loaded, intent, prepare, config, now).await
        }
        _ => Err(Failure("invalid_conversation_intent")),
    }
}
