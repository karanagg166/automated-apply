//! Revocation is durable even when the command itself is denied. Never refund an Apply.
use super::*;
pub(super) async fn move_task(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    mut value: Value,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    value["state"] = json!("PAUSED");
    value["reason"] = json!(reason);
    value["next_action"] = json!("Resume, inspect the current step and authorize fresh fields.");
    value["version"] = json!(
        number(&value, "version")?
            .checked_add(1)
            .ok_or_else(invalid)?
    );
    value["updated_at"] = json!(now.to_rfc3339());
    put(tx, key, &value).await?;
    let audit_key = format!(
        "extension:{}:{}",
        string(&value, "id")?,
        number(&value, "version")?
    );
    let hash = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "{}:{}:{reason}",
                string(&value, "id")?,
                number(&value, "version")?
            )
            .as_bytes()
        )
    );
    let audit = json!({"task_id":value["id"],"application_id":value["application_id"],"state":"PAUSED","reason":reason,"version":value["version"],"submitted":false});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,'owner:primary','extension_task:paused',$2,$3,clock_timestamp()) RETURNING result").bind(audit_key).bind(hash).bind(&audit).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&audit) {
        return Err(Failure("browser_profile_write_ack_failed"));
    }
    Ok(())
}
async fn associated(
    tx: &mut Transaction<'_, Postgres>,
    identity: &Value,
) -> Result<Vec<(String, Value)>> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE ((starts_with(key,'ext_task:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED'))) OR (starts_with(key,'fill_plan:') AND value->>'state' IN ('preview','authorized')) OR (starts_with(key,'chr_cmd:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown')))) AND coalesce(value->'profile_binding_id','null'::jsonb) = $1::jsonb ORDER BY created_at,key LIMIT 10001").bind(identity).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(rows)
}
pub(super) async fn invalidate(
    tx: &mut Transaction<'_, Postgres>,
    identity: &Value,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    for (key, mut value) in associated(tx, identity).await? {
        if key.starts_with("ext_task:") && !task_terminal(&value) {
            if value["state"] == "FILLING" {
                let receipts = value["verified_receipts"]
                    .as_array_mut()
                    .ok_or_else(invalid)?;
                // Preserve exact old authority references as unknown evidence, never a receipt.
                let mut receipts = receipts.clone();
                receipts.push(json!({"plan_id":value["plan_id"],"authorization_id":value["authorization_id"],"packet_revision":value["packet_revision"],"profile_version":value["profile_version"],"verification_method":"unknown","state":"manual_required","results":[],"reason":reason,"recorded_at":now.to_rfc3339(),"submitted":false}));
                let start = receipts.len().saturating_sub(50);
                value["verified_receipts"] = json!(&receipts[start..]);
            }
            let stop_reason = match value["reason"].as_str() {
                Some("owner_pause") => "owner_pause",
                Some("global_stop") => "global_stop",
                _ => reason,
            }
            .to_owned();
            value["plan_id"] = Value::Null;
            value["authorization_id"] = Value::Null;
            value["browser_connection"] = json!("disconnected");
            value["tab_active"] = json!(false);
            move_task(tx, &key, value, &stop_reason, now).await?;
        } else if key.starts_with("fill_plan:")
            && matches!(value["state"].as_str(), Some("preview" | "authorized"))
        {
            value["state"] = json!("read_only");
            value["approved_fields"] = json!([]);
            value["expires_at"] = json!(now.to_rfc3339());
            put(tx, &key, &value).await?;
        } else if key.starts_with("chr_cmd:") && !terminal(&value) {
            value["state"] = json!(if matches!(
                value["state"].as_str(),
                Some("leased" | "executing")
            ) {
                "outcome_unknown"
            } else {
                "cancelled"
            });
            value["reason"] = json!(reason);
            value["version"] = json!(
                number(&value, "version")?
                    .checked_add(1)
                    .ok_or_else(invalid)?
            );
            put(tx, &key, &value).await?;
        }
    }
    Ok(())
}
pub(super) async fn expire(
    tx: &mut Transaction<'_, Postgres>,
    profile: Option<(&Value, &Value)>,
    now: DateTime<Utc>,
) -> Result<()> {
    for (key, mut value) in active_commands(tx, profile.map(|(p, _)| &p["id"])).await? {
        if terminal(&value) {
            continue;
        }
        if profile.is_some_and(|(p, _)| value["profile_binding_id"] != p["id"]) {
            continue;
        }
        let mut expired = timestamp(&value["expires_at"])? <= now;
        if let Some((p, selected)) = profile {
            expired |= value["selection_version"] != selected["version"]
                || value["browser_session_id"] != p["browser_session_id"]
                || value["expected_profile_version"] != p["version"];
            if !value["lease_expires_at"].is_null() {
                expired |= timestamp(&value["lease_expires_at"])? <= now;
            }
        }
        if expired {
            value["state"] = json!(if matches!(
                value["state"].as_str(),
                Some("leased" | "executing")
            ) {
                "outcome_unknown"
            } else {
                "expired"
            });
            value["reason"] = json!(if profile.is_some() {
                "expired_or_profile_changed"
            } else {
                "command_expired"
            });
            value["version"] = json!(
                number(&value, "version")?
                    .checked_add(1)
                    .ok_or_else(invalid)?
            );
            put(tx, &key, &value).await?;
        }
    }
    Ok(())
}
pub(super) async fn session_replaced(
    tx: &mut Transaction<'_, Postgres>,
    profile: &Value,
    window_only: bool,
    now: DateTime<Utc>,
    settings: &Settings,
) -> Result<()> {
    // Select only pending old documents. Historical admissions and receipt keys stay immutable.
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->'form_pending'='true'::jsonb AND value->'form_binding'->'profile_binding_id'=$1 AND value->'form_binding'->'browser_session_id'=$2 AND ($3::jsonb='null'::jsonb OR value->'form_binding'->'window_id'=$3) AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') ORDER BY key LIMIT 10001").bind(&profile["id"]).bind(&profile["browser_session_id"]).bind(&profile["window_id"]).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    for (key, mut value) in rows {
        if !value["form_loss_observation"].is_null() {
            continue;
        }
        if value["admitted_actions"]
            .as_array()
            .is_none_or(Vec::is_empty)
            || !value["form_binding"].is_object()
        {
            return Err(Failure("original_form_loss_binding_required"));
        }
        let original_tab = value["form_binding"]["tab_id"].clone();
        value["stage"] = json!("SUBMISSION_UNKNOWN");
        value["status"] = json!("unknown");
        value["operation"] = json!("reconcile_application");
        value["reason"] = json!("original_questionnaire_context_replaced_reconcile_only");
        value["revision"] = json!(
            number(&value, "revision")?
                .checked_add(1)
                .ok_or_else(invalid)?
        );
        value["updated_at"] = json!(now.to_rfc3339());
        value["lease_token"] = Value::Null;
        value["lease_until"] = Value::Null;
        value["form_loss_observation"] = json!({"at":now.to_rfc3339(),"source":if window_only{"authenticated_browser_window_replaced"}else{"authenticated_browser_session_replaced"},"original_tab_id":original_tab,"replay_authorized":false});
        put(tx, &key, &value).await?;
        for (qkey, mut question) in prefix(tx, "exec_q:").await? {
            if question["queue_work_id"] == value["id"]
                && matches!(
                    question["state"].as_str(),
                    Some("pending" | "sent" | "delivery_unknown")
                )
            {
                question["state"] = json!("closed_form_unavailable");
                question["closed_at"] = json!(now.to_rfc3339());
                question["reuse_approved"] = json!(false);
                put(tx, &qkey, &question).await?;
            }
        }
        let name = "original_form_lost_reconcile_only_no_replay";
        let identity = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "queue:{}:{}:{name}",
                string(&value, "id")?,
                number(&value, "revision")?
            )
            .as_bytes(),
        );
        put(tx,&format!("apply_event:{identity}"),&json!({"id":identity,"queue_id":value["id"],"platform":value["platform"],"stage":value["stage"],"event":name,"at":now.to_rfc3339(),"delivered":false})).await?;
        notify_unknown(tx, &key, &mut value, settings, now).await?;
    }
    Ok(())
}
async fn notify_unknown(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &mut Value,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<()> {
    if !value["uncertain_outcome_notice"].is_null()
        || value["reconciliation_attempts"]
            .as_i64()
            .unwrap_or(0)
            .max(value["account_recheck_attempts"].as_i64().unwrap_or(0))
            < 3
    {
        return Ok(());
    }
    let config = get(tx, "application_queue_policy")
        .await?
        .unwrap_or_else(|| json!({"policy":{}}));
    let enabled = match config["policy"].get("notify_submitted") {
        None => true,
        Some(v) => crate::resource_contract::boolean(v).map_err(|_| invalid())? == true,
    };
    if !enabled {
        return Ok(());
    }
    let prefs = crate::notification_preferences::load_in(tx).await?;
    let title = "Naukri submission remains unconfirmed";
    let body = format!(
        "{} at {}: bounded account/history checks did not verify a sent receipt. This attempt is quarantined and Apply will not be repeated.",
        string(value, "title")?,
        string(value, "company")?
    );
    let dedup = format!("naukri-unknown:{}", string(value, "id")?);
    let mut channels = Vec::new();
    if prefs["paused"] == false && prefs["in_app"] == true {
        let href = format!("/applications/{}", string(value, "packet_id")?);
        sqlx::query("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href,created_at,updated_at) VALUES($1,$2,'application_submission_unknown',$3,$4,$5,clock_timestamp(),clock_timestamp()) ON CONFLICT(dedup_key) DO NOTHING").bind(Uuid::new_v4()).bind(&dedup).bind(title).bind(&body).bind(href).execute(&mut **tx).await.map_err(db)?;
        let ack:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1 AND kind='application_submission_unknown')").bind(&dedup).fetch_one(&mut **tx).await.map_err(db)?;
        if !ack {
            return Err(Failure("browser_profile_write_ack_failed"));
        }
        channels.push("in_app");
    }
    let telegram = match config["policy"]["platforms"]["naukri"].get("notify_telegram") {
        None => false,
        Some(v) => crate::resource_contract::boolean(v).map_err(|_| invalid())? == true,
    };
    if telegram && settings.telegram_notices {
        let hash = format!("{:x}", Sha256::digest(dedup.as_bytes()));
        let id = -i64::from_str_radix(&hash[..15], 16).map_err(|_| invalid())? - (1_i64 << 61);
        sqlx::query("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'pending',$2) ON CONFLICT(update_id) DO NOTHING").bind(id).bind(format!("{title}: {body}")).execute(&mut **tx).await.map_err(db)?;
        let ack: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM agent_telegram_deliveries WHERE update_id=$1)",
        )
        .bind(id)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
        if !ack {
            return Err(Failure("browser_profile_write_ack_failed"));
        }
        channels.push("telegram_outbox");
    }
    if !channels.is_empty() {
        value["uncertain_outcome_notice"] = json!({"at":now.to_rfc3339(),"channels":channels,"dedup_key":dedup,"verified_submission":false});
        put(tx, key, value).await?;
    }
    Ok(())
}
