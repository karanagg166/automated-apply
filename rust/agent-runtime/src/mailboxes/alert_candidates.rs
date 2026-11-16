//! Cross-mailbox requisition identity; authenticated email links do not create vacancies/jobs.
use super::{
    alerts::{at, db, get, invalid, put},
    *,
};
use sqlx::{Postgres, Transaction};
pub(super) async fn retain(
    tx: &mut Transaction<'_, Postgres>,
    slot: Slot,
    account: &Value,
    message: &Value,
    now: DateTime<Utc>,
    telegram: Option<&crate::telegram::Settings>,
) -> Result<(usize, usize)> {
    let evidence = crate::mail_evidence::content_evidence(&message["payload"])?;
    let candidates = alert_rules::links(&evidence["links"])?;
    if candidates.is_empty() {
        return Ok((0, 0));
    }
    sqlx::query("SELECT pg_advisory_xact_lock(407054,2)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let patterns = candidates
        .iter()
        .map(|(req, _)| format!("-{req}/?([?#].*)?$"))
        .collect::<Vec<_>>();
    let jobs:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j)||jsonb_build_object('uncertain',EXISTS(SELECT 1 FROM application_packets p WHERE p.job_id=j.id AND p.lifecycle_state IN ('submitting','submission_unknown')),'applied',j.status IN ('applied','submitted') OR j.discovery_metadata::jsonb#>>'{data_provenance,posting_status}'='already_applied' OR EXISTS(SELECT 1 FROM application_packets p WHERE p.job_id=j.id AND p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted'))) FROM jobs j WHERE j.source_platform='naukri' AND j.job_url ~ ANY($1::text[]) ORDER BY j.id LIMIT 10001").bind(&patterns).fetch_all(&mut **tx).await.map_err(db)?;
    if jobs.len() > 10000 {
        return Err(Failure("gmail_alert_candidate_inventory_limit"));
    }
    let receipt_keys = candidates
        .iter()
        .flat_map(|(req, _)| {
            [
                format!("naukri_receipt:{req}"),
                format!("naukri_worker_receipt:{req}"),
            ]
        })
        .collect::<Vec<_>>();
    let history_keys: Vec<String> =
        sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key=ANY($1::text[])")
            .bind(&receipt_keys)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let requisitions = candidates
        .iter()
        .map(|(req, _)| req.clone())
        .collect::<Vec<_>>();
    let work:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'requisition'=ANY($1::text[]) ORDER BY key LIMIT 10001").bind(&requisitions).fetch_all(&mut **tx).await.map_err(db)?;
    if work.len() > 10000 {
        return Err(Failure("gmail_alert_candidate_inventory_limit"));
    }
    let mut added = 0;
    for (req, url) in &candidates {
        let lead_key = format!("gm54_lead:{}", &digest(req)[..32]);
        let mut lead=get(tx,&lead_key).await?.unwrap_or(json!({"requisition":req,"url":url,"sources":[],"state":"NEEDS_FACTUAL_AND_ORIGIN_REVIEW","origin_authenticated":false,"submitted":false}));
        let reference =
            json!({"source":"gmail","account":account["account_email"],"message_id":message["id"]});
        let sources = lead["sources"].as_array_mut().ok_or_else(invalid)?;
        if !sources.contains(&reference) {
            if sources.len() >= 100 {
                return Err(Failure("job_alert_source_reference_limit"));
            }
            sources.push(reference);
        }
        lead["observed_at"] = json!(now);
        put(tx, &lead_key, &lead).await?;
        let matching = jobs
            .iter()
            .filter(|job| {
                job["job_url"]
                    .as_str()
                    .and_then(|url| crate::execution::filters::naukri_url(url).ok())
                    .is_some_and(|url| url.rsplit('-').next() == Some(req.as_str()))
            })
            .collect::<Vec<_>>();
        let applied = matching.iter().any(|job| job["applied"] == true);
        let uncertain = matching.iter().any(|job| job["uncertain"] == true)
            || work.iter().any(|w| {
                w["requisition"] == *req
                    && (matches!(w["stage"].as_str(), Some("SUBMISSION_UNKNOWN" | "APPLYING"))
                        || w["admitted_actions"].as_array().is_some_and(|a| {
                            a.iter().any(|v| {
                                v["fingerprint"]
                                    .as_str()
                                    .is_some_and(|s| s.starts_with("apply:"))
                            })
                        }))
            })
            || history_keys
                .iter()
                .any(|key| key.rsplit(':').next() == Some(req.as_str()));
        let existing = matching.first();
        let state = if applied {
            "ALREADY_APPLIED"
        } else if uncertain {
            "HISTORY_REVIEW_REQUIRED"
        } else if existing.is_some() {
            "EXISTING_JOB"
        } else {
            "NEEDS_INPUT"
        };
        let identity = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("gmail-naukri-alert:{req}").as_bytes(),
        );
        let key = format!("nau_alert:{identity}");
        let old = get(tx, &key).await?;
        if let Some(old) = old.as_ref().filter(|v| v["state"] != "EXPIRED") {
            at(&old["expires_at"])?;
        }
        let reference = format!("gmail:{}:{}", slot.name(), text(message, "id")?);
        let value = if let Some(mut old) =
            old.filter(|v| v["state"] != "EXPIRED" && at(&v["expires_at"]).is_ok_and(|at| at > now))
        {
            let mut references = old["message_references"]
                .as_array()
                .ok_or_else(invalid)?
                .clone();
            if !references.contains(&json!(reference)) {
                references.push(json!(reference));
            }
            if references.len() > 10 {
                references.drain(..references.len() - 10);
            }
            old["last_observation"] = json!(now);
            old["message_references"] = json!(references);
            if applied {
                old["state"] = json!("ALREADY_APPLIED");
                old["reason"] = json!("already_applied");
            } else if uncertain {
                old["state"] = json!("HISTORY_REVIEW_REQUIRED");
                old["reason"] = json!("prior_or_uncertain_application");
            }
            old
        } else {
            added += 1;
            let value = json!({"id":identity,"account_id":format!("local:{}",slot.name()),"requisition_id":req,"url":url,"state":state,"title":null,"employer":null,"reason":if applied{"already_applied"}else if uncertain{"prior_or_uncertain_application"}else if existing.is_some(){"existing_saved_job"}else{"verified_vacancy_facts_required"},"source":"gmail_job_alerts","message_references":[reference],"received_at":now,"last_observation":now,"expires_at":now+Duration::days(14),"posting_status":"unknown","sender_authenticity":"gmail_reported_dmarc_and_dkim_pass","submitted":false,"job_id":existing.map(|j|j["id"].clone())});
            if state == "NEEDS_INPUT" {
                notice(tx, identity, req, telegram).await?;
            }
            value
        };
        put(tx, &key, &value).await?;
    }
    Ok((added, candidates.len()))
}
async fn notice(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    requisition: &str,
    telegram: Option<&crate::telegram::Settings>,
) -> Result<()> {
    let key = format!("gmail-alert:{identity}");
    let prefs = crate::notification_preferences::load_in(tx).await?;
    if prefs["in_app"] == true && prefs["paused"] != true {
        let notification = Uuid::new_v5(&Uuid::NAMESPACE_URL, key.as_bytes());
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href,created_at) VALUES($1,$2,'job_match','Naukri alert candidate requires vacancy facts','Authenticated Naukri alert contains a direct requisition link. Employer facts and active vacancy remain unverified.','/jobs',clock_timestamp()) ON CONFLICT(dedup_key) DO NOTHING RETURNING id").bind(notification).bind(&key).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack.is_none() {
            let exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1)",
            )
            .bind(&key)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
            if !exists {
                return Err(Failure("gmail_alert_write_ack_failed"));
            }
        } else if ack != Some(notification) {
            return Err(Failure("gmail_alert_write_ack_failed"));
        }
    }
    if let Some(telegram) = telegram {
        let available:bool=sqlx::query_scalar("SELECT to_regclass('rust_telegram_runtime') IS NOT NULL AND to_regclass('rust_telegram_outbox') IS NOT NULL AND to_regclass('agent_telegram_deliveries') IS NOT NULL").fetch_one(&mut **tx).await.map_err(db)?;
        if available {
            crate::telegram::bound(tx, telegram).await?;
            let update = -i64::from_str_radix(&digest(&key)[..15], 16).map_err(|_| invalid())?
                - (1_i64 << 60);
            let reply = format!(
                "Naukri alert candidate {requisition}: saved for factual vacancy review. No fields filled or application sent. Open Jobs in Automated Apply."
            );
            let inserted:Option<i64>=sqlx::query_scalar("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'pending',$2) ON CONFLICT(update_id) DO NOTHING RETURNING update_id").bind(update).bind(&reply).fetch_optional(&mut **tx).await.map_err(db)?;
            if inserted == Some(update) {
                let intent = Uuid::new_v5(
                    &Uuid::NAMESPACE_URL,
                    format!("gmail_alert_notice:{update}").as_bytes(),
                );
                let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO rust_telegram_outbox(id,update_id,binding,reply,state) VALUES($1,$2,$3,$4,'pending') RETURNING id").bind(intent).bind(update).bind(telegram.binding()).bind(reply).fetch_optional(&mut **tx).await.map_err(db)?;
                if ack != Some(intent) {
                    return Err(Failure("gmail_alert_write_ack_failed"));
                }
            } else if inserted.is_some() {
                return Err(Failure("gmail_alert_write_ack_failed"));
            } else {
                let exists: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM agent_telegram_deliveries WHERE update_id=$1)",
                )
                .bind(update)
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
                if !exists {
                    return Err(Failure("gmail_alert_write_ack_failed"));
                }
            }
        }
    }
    Ok(())
}
