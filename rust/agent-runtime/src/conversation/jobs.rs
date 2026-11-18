//! Select saved jobs for a preview and recheck their current state before preparation.
use super::{filters, intent::Intent, preferences};
use crate::{Failure, Result};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

fn db(_: sqlx::Error) -> Failure {
    Failure("conversation_jobs_database_error")
}

pub(super) struct Job {
    pub id: Uuid,
    pub data: Value,
    pub public_url: String,
}

pub(super) struct Search {
    pub jobs: Vec<Job>,
    pub limited: bool,
    pub clarification: Option<Vec<String>>,
}

pub(super) async fn policy(tx: &mut Transaction<'_, Postgres>) -> Result<Option<Value>> {
    crate::platform_policy::saved(tx).await
}

pub(super) fn preview_allowed(policy: Option<&Value>, url: &str) -> Result<bool> {
    let platform = crate::browser_profiles::commands::page_kind(url)?;
    Ok(crate::platform_policy::preference(policy, platform)? != "disabled")
}

fn display_url(raw: &str) -> Option<String> {
    let mut url = reqwest::Url::parse(&crate::resources::public_https(raw)?).ok()?;
    url.set_query(None);
    url.set_fragment(None);
    Some(url.to_string())
}

async fn disambiguate_company(
    tx: &mut Transaction<'_, Postgres>,
    intent: &mut Intent,
) -> Result<Option<Vec<String>>> {
    if intent.company.is_some() {
        return Ok(None);
    }
    let Some(role) = intent.role.as_deref() else {
        return Ok(None);
    };
    let names: Vec<String> =
        sqlx::query_scalar("SELECT name FROM companies ORDER BY name, id LIMIT 201")
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let folded_role = folded(role);
    let candidates: Vec<_> = names
        .into_iter()
        .filter(|name| {
            let name = folded(name);
            !name.is_empty()
                && (folded_role == name || folded_role.starts_with(&format!("{name} ")))
        })
        .take(5)
        .collect();
    if candidates.len() > 1 {
        return Ok(Some(candidates));
    }
    if let Some(name) = candidates.into_iter().next() {
        let suffix: String = role.chars().skip(name.chars().count()).collect();
        intent.role = (!suffix.trim().is_empty()).then(|| suffix.trim().to_owned());
        intent.company = Some(name);
        super::intent::normalize(
            serde_json::to_value(&*intent).map_err(|_| Failure("invalid_conversation_intent"))?,
        )?;
    }
    Ok(None)
}

pub(super) async fn search(
    tx: &mut Transaction<'_, Postgres>,
    intent: &mut Intent,
    ids: Option<&[Uuid]>,
    prepare: bool,
    now: DateTime<Utc>,
) -> Result<Search> {
    if ids.is_none()
        && let Some(candidates) = disambiguate_company(tx, intent).await?
    {
        return Ok(Search {
            jobs: vec![],
            limited: false,
            clarification: Some(candidates),
        });
    }
    let preferences = preferences::effective(tx).await?;
    let policy = policy(tx).await?;
    let suppress_history = ids.is_some()
        || prepare
        || intent.not_applied
        || preferences["application_status"] == "not_applied";
    let history = if suppress_history {
        crate::execution::reviewed_history::load_in(tx, now).await?
    } else {
        vec![]
    };
    let rows: Vec<(Option<Value>, Option<Value>, bool)> =
        sqlx::query_as(include_str!("../../sql/conversation_jobs.sql"))
            .bind(ids)
            .bind(intent.company.as_deref().map(folded))
            .bind(suppress_history)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let limited = rows.len() > 200;
    let mut jobs = Vec::new();
    for (data, company, has_history) in rows.into_iter().take(200) {
        let Some(data) = data else {
            continue;
        };
        if suppress_history
            && (has_history
                || crate::execution::reviewed_history::previously_applied(
                    &data,
                    company.as_ref(),
                    &history,
                ))
        {
            continue;
        }
        if !filters::matches(
            &data,
            company.as_ref().unwrap_or(&Value::Null),
            intent,
            &preferences,
            now,
        ) {
            continue;
        }
        let Some(public_url) = data["job_url"].as_str().and_then(display_url) else {
            continue;
        };
        if !preview_allowed(policy.as_ref(), &public_url)? {
            continue;
        }
        let id = data["id"]
            .as_str()
            .and_then(|id| id.parse().ok())
            .ok_or(Failure("invalid_saved_job_record"))?;
        jobs.push(Job {
            id,
            data,
            public_url,
        });
        if jobs.len() == 10 {
            break;
        }
    }
    Ok(Search {
        jobs,
        limited,
        clarification: None,
    })
}

pub(super) async fn prepare(
    tx: &mut Transaction<'_, Postgres>,
    job: &Job,
    config: &crate::configuration::Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let Some(destination) = job.data["application_url"]
        .as_str()
        .or(job.data["job_url"].as_str())
        .and_then(crate::resources::public_https)
    else {
        return Ok(
            json!({"status":"denied","reply":"The saved application destination needs review.","submitted":false}),
        );
    };
    if !preview_allowed(policy(tx).await?.as_ref(), &destination)? {
        return Ok(
            json!({"status":"denied","reply":"The application destination is disabled in your saved policy.","submitted":false}),
        );
    }
    let owner: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM candidate_profiles WHERE singleton_key = 'primary'")
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    let Some(owner) = owner else {
        return Ok(
            json!({"status":"preparation_preview","job_id":job.id,"reply":"Set up your candidate profile in the dashboard to prepare this saved job.","submitted":false}),
        );
    };
    let existing: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM application_packets WHERE job_id = $1 AND candidate_profile_id = $2",
    )
    .bind(job.id)
    .bind(owner)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let packet = match existing {
        Some(id) => crate::packet_service::read_locked_in(tx, id, &config.packets, now).await?,
        None => {
            let request = crate::packet_contract::normalize(
                json!({"idempotency_key":format!("telegram-prepare-{}", job.id)}),
                true,
            )?;
            crate::packet_service::create_locked_in(
                tx,
                job.id,
                &request,
                &config.packets,
                &config.answers,
                now,
            )
            .await?
        }
    };
    let readiness = packet["readiness"]["state"]
        .as_str()
        .ok_or(Failure("invalid_packet_record"))?;
    Ok(json!({
        "status":"prepared_for_review","packet_id":packet["id"],"job_id":job.id,"readiness":readiness,
        "reply":format!("Application prepared for review. Readiness: {readiness}. Open the dashboard."),
        "submitted":false
    }))
}
