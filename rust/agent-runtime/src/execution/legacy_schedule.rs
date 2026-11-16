//! Bounded legacy preparation scheduling and expiry maintenance on the existing execution connection.
use super::{
    contracts::{self, Kind},
    legacy_policy, legacy_prepare, legacy_work, owner_routes, review, reviewed_history,
    storage::*,
};
use crate::{Failure, Result, configuration::Configuration, packet_service};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)
}
fn authority_denial(error: Failure) -> bool {
    matches!(
        error.0,
        "confirmed_profile_version_required"
            | "approved_primary_resume_changed_or_missing"
            | "verified_experience_outside_policy"
            | "gmail_intake_deferred_to_phase54"
    )
}
async fn recurring_in(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<bool> {
    let mut value = legacy_policy::record(tx).await?;
    if value["state"] != "RUNNING"
        || legacy_policy::configuration(tx).await?["mode"] == "OFF"
        || !value["next_check_at"].is_null() && timestamp(&value["next_check_at"])? > now
    {
        return Ok(false);
    }
    let policy = contracts::normalize(Kind::AutomationPolicy, value["policy"].clone())
        .map_err(|_| invalid())?;
    value["last_check_at"] = json!(stamp(now));
    value["next_check_at"] = json!(stamp(
        now + chrono::Duration::seconds(policy["interval_seconds"].as_i64().ok_or_else(invalid)?)
    ));
    if let Err(error) = legacy_policy::validate_in(tx, &policy).await {
        if authority_denial(error) {
            value["blocked_reason"] = json!(error.0);
            put(tx, "naukri_automation", &value).await?;
            return Ok(true);
        }
        return Err(error);
    }
    let cursor = if value["cursor"].is_null() {
        None
    } else {
        Some(id(&value["cursor"])?)
    };
    let (jobs, decisions) = review::batch_in(tx, cursor, now).await?;
    value["cursor"] = if jobs.len() == 100 {
        jobs.last().ok_or_else(invalid)?["id"].clone()
    } else {
        Value::Null
    };
    let key = format!("nau_budget:{}", now.date_naive());
    let budget = get(tx, &key).await?;
    let mut used = match budget {
        Some(value) => value["reserved"]
            .as_i64()
            .filter(|n| *n >= 0)
            .ok_or_else(invalid)?,
        None => 0,
    };
    let cap = policy["max_preparations_per_day"]
        .as_i64()
        .filter(|n| *n >= 1)
        .ok_or_else(invalid)?;
    for (job, mut decision) in jobs.into_iter().zip(decisions) {
        let evaluated = super::legacy_policy::reason(&job, &decision, &policy, now)?;
        let eligible = evaluated.is_none();
        let mut reason = evaluated;
        if reason.is_none() {
            let url = super::filters::naukri_url(job["job_url"].as_str().ok_or_else(invalid)?)?;
            let identity = Uuid::new_v5(
                &Uuid::NAMESPACE_URL,
                format!("naukri:{}", url.rsplit('-').next().ok_or_else(invalid)?).as_bytes(),
            );
            if get(tx, &format!("exec:{identity}")).await?.is_some() {
                reason = Some("existing_intent_no_automatic_resume".into());
            } else if used >= cap {
                reason = Some("daily_preparation_limit".into());
            } else {
                let started =
                    owner_routes::start_in(tx, json!({"job_ids":[job["id"]]}), now).await?;
                let mut intent = started[0].clone();
                intent["automation_revision"] = value["revision"].clone();
                legacy_work::save_in(tx, &intent).await?;
                used = used.checked_add(1).ok_or_else(invalid)?;
            }
        }
        decision["reason"] = json!(reason.unwrap_or_else(|| "bounded_preparation_queued".into()));
        decision["eligible"] = json!(eligible);
        decision["policy_revision"] = value["revision"].clone();
        decision["evaluated_at"] = json!(stamp(now));
        decision["source"] = job["discovery_metadata"]["data_provenance"]
            .get("method")
            .cloned()
            .unwrap_or(json!("owner_url"));
        decision["source_reference"] =
            job["discovery_metadata"]["data_provenance"]["reference"].clone();
        decision["last_observation"] =
            job["discovery_metadata"]["data_provenance"]["owner_observed_at"].clone();
        put(tx, &format!("nau_dec:{}", id(&job["id"])?), &decision).await?;
    }
    put(tx, &key, &json!({"reserved":used,"day_timezone":"UTC"})).await?;
    value["blocked_reason"] = json!(if policy["source"] == "saved_owner_imports" {
        "recurring_external_source_not_connected"
    } else {
        "email_vacancy_facts_require_owner_review"
    });
    put(tx, "naukri_automation", &value).await?;
    Ok(true)
}
async fn maintain_in(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<bool> {
    let automation = legacy_policy::record(tx).await?;
    let active =
        automation["state"] == "RUNNING" && automation["policy"]["telegram_questions"] == true;
    let marker = get(tx, "exec_maintenance:naukri")
        .await?
        .unwrap_or(Value::Null);
    let cursor = marker["key"].as_str();
    let created = if cursor.is_some() {
        Some(timestamp(&marker["created_at"])?)
    } else {
        None
    };
    let rows:Vec<(String,Value,DateTime<Utc>)>=sqlx::query_as("SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'exec:') AND value->>'packet_id' IS NOT NULL AND (value->>'state'='READY_FOR_REVIEW' OR (value->>'state'='NEEDS_INPUT' AND $1 AND value->'automation_revision'=$2)) AND ($3::timestamptz IS NULL OR (created_at,key)>($3,$4)) ORDER BY created_at,key LIMIT 10").bind(active).bind(&automation["revision"]).bind(created).bind(cursor).fetch_all(&mut **tx).await.map_err(db)?;
    let mut changed = false;
    for (_, mut intent, _) in rows.iter().cloned() {
        let packet =
            packet_service::read_locked_in(tx, id(&intent["packet_id"])?, &config.packets, now)
                .await?;
        if intent["state"] == "READY_FOR_REVIEW" && packet["readiness"]["stale"] != true {
            let mut expired = false;
            for field in packet["fields"].as_array().ok_or_else(invalid)? {
                if field["field_type"] != "file"
                    && (field["required"] == true
                        && field["effective_answer"].as_str().is_none_or(str::is_empty)
                        || !field["provenance"]["answer_expires_at"].is_null()
                            && timestamp(&field["provenance"]["answer_expires_at"])? <= now)
                {
                    expired = true;
                    break;
                }
            }
            if expired {
                legacy_work::move_in(
                    tx,
                    &mut intent,
                    "NEEDS_INPUT",
                    Some("owner_question_approval_required"),
                    now,
                )
                .await?;
                changed = true;
            }
        }
        if active && intent["automation_revision"] == automation["revision"] {
            legacy_prepare::questions_in(
                tx,
                &mut intent,
                &packet,
                Some(&automation["policy"]),
                config,
                now,
            )
            .await?;
        }
    }
    if !rows.is_empty() || cursor.is_some() {
        let next = if rows.len() == 10 {
            let (key, _, created) = rows.last().ok_or_else(invalid)?;
            json!({"key":key,"created_at":stamp(*created)})
        } else {
            json!({"key":null,"created_at":null})
        };
        put(tx, "exec_maintenance:naukri", &next).await?;
    }
    Ok(changed)
}
pub(crate) async fn tick(c: &mut PgConnection, config: &Configuration) -> Result<bool> {
    let hint:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences o WHERE (o.key='naukri_automation' AND o.value->>'state'='RUNNING' AND (o.value->>'next_check_at' IS NULL OR CASE WHEN pg_input_is_valid(o.value->>'next_check_at','timestamp with time zone') THEN (o.value->>'next_check_at')::timestamptz<=clock_timestamp() ELSE true END)) OR (o.key='exec_config:naukri' AND o.value->>'mode'='WATCH_AND_NOTIFY' AND NOT EXISTS(SELECT 1 FROM owner_preferences w WHERE w.key='exec_watch:naukri' AND CASE WHEN pg_input_is_valid(w.value->>'next_at','timestamp with time zone') THEN (w.value->>'next_at')::timestamptz>clock_timestamp() ELSE false END)) OR (starts_with(o.key,'exec:') AND o.value->>'packet_id' IS NOT NULL AND (o.value->>'state'='READY_FOR_REVIEW' OR (o.value->>'state'='NEEDS_INPUT' AND EXISTS(SELECT 1 FROM owner_preferences a WHERE a.key='naukri_automation' AND a.value->>'state'='RUNNING' AND a.value#>>'{policy,telegram_questions}'='true' AND o.value->'automation_revision'=a.value->'revision')))))").fetch_one(&mut *c).await.map_err(db)?;
    if !hint {
        return Ok(false);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let seeded = recurring_in(&mut tx, now).await?;
        let maintained = maintain_in(&mut tx, config, now).await?;
        let watched = watch_in(&mut tx, now).await?;
        Ok(seeded || maintained || watched)
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}

async fn watch_in(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<bool> {
    if let Err(error) = legacy_policy::enabled(tx).await {
        if matches!(
            error.0,
            "naukri_automation_paused" | "naukri_automation_stopped" | "execution_mode_off"
        ) {
            return Ok(false);
        }
        return Err(error);
    }
    let config = legacy_policy::configuration(tx).await?;
    if config["mode"] != "WATCH_AND_NOTIFY" {
        return Ok(false);
    }
    if let Some(marker) = get(tx, "exec_watch:naukri").await? {
        if timestamp(&marker["next_at"])? > now {
            return Ok(false);
        }
    }
    put(tx,"exec_watch:naukri",&json!({"next_at":stamp(now+chrono::Duration::seconds(config["interval_seconds"].as_i64().ok_or_else(invalid)?)),"heartbeat_at":stamp(now)})).await?;
    let profile = match crate::profile_store::get(tx).await {
        Ok(profile) => profile.value,
        Err(Failure("profile_not_found")) => return Ok(false),
        Err(error) => return Err(error),
    };
    let prefs = crate::notification_preferences::load_in(tx).await?;
    if prefs["paused"] == true || prefs["in_app"] != true {
        return Ok(false);
    }
    let rows:Vec<(Value,Option<Value>)>=sqlx::query_as("SELECT to_jsonb(j),CASE WHEN c.id IS NULL THEN NULL ELSE jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) END FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE j.source_platform='naukri' ORDER BY j.created_at DESC,j.id LIMIT 100").fetch_all(&mut **tx).await.map_err(db)?;
    let history = reviewed_history::load_in(tx, now).await?;
    let mut count = 0;
    for (job, company) in rows {
        if super::history::provider_applied_in(tx, &job).await? {
            continue;
        }
        let reviewed = crate::job_context::Reviewed::new(job.clone(), company.clone())?;
        let history_match = reviewed_history::previously_applied(
            reviewed.job_view(),
            reviewed.employer(),
            &history,
        );
        let decision = review::decision_with_history(
            job,
            company,
            Some(&profile),
            true,
            false,
            history_match,
            now,
        )?;
        let fit: automated_apply_domain::matching::DiscoveryMatch =
            serde_json::from_value(decision["match"].clone()).map_err(|_| invalid())?;
        if review::preparation_eligibility(reviewed.job_view(), &profile, &fit, now)?.0
            != "ELIGIBLE"
        {
            continue;
        }
        let job = id(&decision["id"])?;
        let key = format!(
            "naukri_watch:{job}:{}",
            profile["version"].as_i64().ok_or_else(invalid)?
        );
        let notification = Uuid::new_v4();
        let body = format!(
            "{}: imported facts match saved preferences; review vacancy and eligibility.",
            reviewed.job_view()["title"].as_str().ok_or_else(invalid)?
        );
        let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,'job_match','Naukri saved opportunity',$3,$4) ON CONFLICT(dedup_key) DO NOTHING RETURNING id").bind(notification).bind(&key).bind(body).bind(format!("/jobs/{job}")).fetch_optional(&mut **tx).await.map_err(db)?;
        if let Some(actual) = inserted {
            if actual != notification {
                return Err(Failure("execution_write_ack_failed"));
            }
            count += 1;
        } else {
            let exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1)",
            )
            .bind(&key)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
            if !exists {
                return Err(Failure("execution_write_ack_failed"));
            }
        }
    }
    Ok(count > 0)
}
