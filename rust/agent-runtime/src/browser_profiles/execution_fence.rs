//! Revoke Naukri packet authority inside the execution controller's owner transaction.
//! No browser calls. Consumed plans and late receipts remain available as audit evidence.
use super::*;

pub(crate) async fn fence_naukri(
    tx: &mut Transaction<'_, Postgres>,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT o.key,o.value FROM owner_preferences o WHERE ((starts_with(o.key,'ext_task:') AND (o.value->>'state' IS NULL OR o.value->>'state' NOT IN ('FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED'))) OR (starts_with(o.key,'fill_plan:') AND o.value->>'state' IN ('preview','authorized')) OR (starts_with(o.key,'chr_cmd:') AND (o.value->>'state' IS NULL OR o.value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown')))) AND EXISTS(SELECT 1 FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE p.id::text=o.value->>'application_id' AND j.source_platform='naukri') ORDER BY o.created_at,o.key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    for (key, mut value) in rows {
        if key.starts_with("ext_task:") {
            let task_reason = if value["reason"] == "global_stop" {
                "global_stop"
            } else {
                reason
            };
            tasks::move_in(
                tx,
                value.clone(),
                "PAUSED",
                task_reason,
                json!({"plan_id":null,"authorization_id":null,"browser_connection":"paused"}),
                now,
            )
            .await?;
        } else if key.starts_with("fill_plan:") {
            value["state"] = json!("read_only");
            value["approved_fields"] = json!([]);
            value["expires_at"] = json!(now.to_rfc3339());
            put(tx, &key, &value).await?;
        } else {
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
