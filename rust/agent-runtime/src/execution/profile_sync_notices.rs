//! Reference-only owner dashboard questions; contact email is never a portal-login correction.
use super::{profile_sync as facts, storage::*};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn missing_in(
    tx: &mut Transaction<'_, Postgres>,
    decisions: &[Value],
) -> Result<()> {
    let active:Vec<(Uuid,String,String)>=sqlx::query_as("SELECT id,dedup_key,body FROM owner_notifications WHERE kind='profile_information_required' AND starts_with(dedup_key,'naukri_profile:') ORDER BY id LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if active.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for decision in decisions {
        let field = decision["field"]
            .as_str()
            .filter(|s| facts::FIELDS.contains(s))
            .ok_or_else(invalid)?;
        if field == "email" || decision["state"] == "UNSUPPORTED" {
            continue;
        }
        let identity=facts::reference(&json!({"field":decision["field"],"state":decision["state"],"previous_reference":decision["previous_reference"],"new_reference":decision["new_reference"]})).ok_or_else(invalid)?;
        let key = format!("naukri_profile:{identity}");
        let field = field.replace('_', " ");
        let needs = matches!(
            decision["state"].as_str(),
            Some(
                "MISSING_FROM_DATABASE"
                    | "MISSING_FROM_PLATFORM"
                    | "MISSING_INFORMATION"
                    | "CONFLICT"
                    | "OUTDATED"
            )
        );
        for (id, old_key, body) in &active {
            if body.starts_with(&format!("Review {field} in your ")) && (!needs || old_key != &key)
            {
                let ack:Option<String>=sqlx::query_scalar("UPDATE owner_notifications SET kind='profile_information_resolved',title='Earlier Naukri profile notice superseded',body=$2,updated_at=clock_timestamp() WHERE id=$1 AND kind='profile_information_required' RETURNING kind").bind(id).bind(format!("The earlier {field} notice has been superseded by a newer portal comparison. Check profile reconciliation for the current state; no fact was overwritten.")).fetch_optional(&mut **tx).await.map_err(db)?;
                if ack.as_deref() != Some("profile_information_resolved") {
                    return Err(Failure("execution_write_ack_failed"));
                }
            }
        }
        if !needs {
            continue;
        }
        let target = if decision["state"] == "MISSING_FROM_DATABASE" {
            "saved profile"
        } else {
            "Naukri profile"
        };
        let body = format!(
            "Review {field} in your {target}. Supply or confirm the correct information in your profile before a supported portal update. Unverified facts will not be invented."
        );
        let id = Uuid::new_v4();
        let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,'profile_information_required','Naukri profile information needs attention',$3,'/profile') ON CONFLICT(dedup_key) DO UPDATE SET kind=excluded.kind,title=excluded.title,body=excluded.body,href=excluded.href,read_at=NULL,updated_at=clock_timestamp() WHERE owner_notifications.kind='profile_information_resolved' RETURNING id").bind(id).bind(&key).bind(body).fetch_optional(&mut **tx).await.map_err(db)?;
        if let Some(id) = inserted {
            let delivery = Uuid::new_v4();
            let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO notification_deliveries(id,notification_id,channel,status,attempt_count) VALUES($1,$2,'in_app','available_in_app',1) ON CONFLICT(notification_id,channel) DO NOTHING RETURNING id").bind(delivery).bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
            if ack.is_none() {
                let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM notification_deliveries WHERE notification_id=$1 AND channel='in_app')").bind(id).fetch_one(&mut **tx).await.map_err(db)?;
                if !exists {
                    return Err(Failure("execution_write_ack_failed"));
                }
            } else if ack != Some(delivery) {
                return Err(Failure("execution_write_ack_failed"));
            }
        } else {
            let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1 AND kind='profile_information_required')").bind(&key).fetch_one(&mut **tx).await.map_err(db)?;
            if !exists {
                return Err(Failure("execution_write_ack_failed"));
            }
        }
    }
    Ok(())
}
