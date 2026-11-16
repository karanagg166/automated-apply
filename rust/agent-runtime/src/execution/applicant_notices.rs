//! Owner-visible choice for an unknown count. No default policy change or inferred upper bound.
use super::{contracts, storage::*};
use crate::{Failure, Result};
use serde_json::Value;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(crate) async fn required_in(tx: &mut Transaction<'_, Postgres>, policy: &Value) -> Result<()> {
    let limits = contracts::limits(policy, "naukri")?;
    if limits["unknown_applicants"] != "needs_review" || limits["applicant_limit"].is_null() {
        return Ok(());
    }
    let threshold = limits["applicant_limit"]
        .as_i64()
        .filter(|n| *n > 0)
        .ok_or_else(invalid)?;
    let key = format!("naukri_applicant_question:{threshold}");
    let id = Uuid::new_v4();
    let title = "Choose how Naukri applicant estimates are handled";
    let body = format!(
        "A label such as 100+ gives a minimum, not proof of fewer than {threshold} applicants. Your current rule holds these jobs. In Naukri queue settings you can keep review, skip, or explicitly allow lower-bound labels below your threshold while reviewing missing counts. Actual counts may exceed the threshold; all other eligibility checks still apply."
    );
    let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,'automation_policy_question',$3,$4,'/naukri') ON CONFLICT(dedup_key) DO UPDATE SET kind=excluded.kind,title=excluded.title,body=excluded.body,href=excluded.href,read_at=NULL,updated_at=clock_timestamp() WHERE owner_notifications.kind='automation_policy_resolved' RETURNING id").bind(id).bind(&key).bind(title).bind(body).fetch_optional(&mut **tx).await.map_err(db)?;
    if let Some(id) = ack {
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
        let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1 AND kind='automation_policy_question')").bind(key).fetch_one(&mut **tx).await.map_err(db)?;
        if !exists {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    Ok(())
}
