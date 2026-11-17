//! Explicit recovery of acknowledged original run data. Never start or abort an Actor.
use super::{
    read_admission::{self, Admission},
    read_session::Session,
    settings::Settings,
    transport::Client,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
}
impl Service<'_> {
    pub async fn recover(&self, c: &mut PgConnection, parent: Uuid, id: Uuid) -> Result<Value> {
        let claim = match read_admission::admit(c, self.settings, parent, id).await? {
            Admission::Retained(v) => return Ok(v),
            Admission::Original(claim) => claim,
        };
        let mut session = Session::original(*claim)?;
        let target = session.context().status_target()?;
        session
            .exchange(
                c,
                self.client,
                self.settings,
                "status",
                target,
                |context, body| {
                    context.accept_status(body, Utc::now())?;
                    Ok(((), context.selected_run()))
                },
            )
            .await?;
        if !session.context().succeeded() {
            return read_admission::read(c, parent, id).await;
        }
        let target = session.context().build_target()?;
        let build = session
            .exchange(
                c,
                self.client,
                self.settings,
                "run_build",
                target,
                |context, body| {
                    let build = context.accept_build(body)?;
                    let selected = build.selected();
                    Ok((build, selected))
                },
            )
            .await?;
        let observed = Utc::now();
        let limit = session.context().plan().query["limit"]
            .as_u64()
            .ok_or(Failure("apify_read_original_checkpoint_invalid"))?;
        for offset in (0..limit).step_by(50) {
            let target = session.context().dataset_target(&build, offset)?;
            let page = session
                .exchange(
                    c,
                    self.client,
                    self.settings,
                    "dataset",
                    target,
                    |context, body| {
                        let page = super::dataset::page(
                            context.plan(),
                            context.run_id(),
                            body,
                            offset,
                            observed,
                        )?;
                        Ok((page.clone(), page))
                    },
                )
                .await?;
            if page["returned"]
                .as_u64()
                .ok_or(Failure("apify_dataset_schema_invalid"))?
                < 50.min(limit - offset)
            {
                break;
            }
        }
        finish(c, self.settings, parent, id).await
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_read_database_error")
}
fn ack() -> Failure {
    Failure("apify_read_write_ack_failed")
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
/// Recover only local finding work from saved complete pages. No read grant or HTTP client exists here.
pub async fn finish(
    c: &mut PgConnection,
    settings: &Settings,
    parent: Uuid,
    id: Uuid,
) -> Result<Value> {
    let mut tx = super::admission::transaction(c).await?;
    let now = clock(&mut tx).await?;
    let prior = read_admission::read_in(&mut tx, parent, id, now).await?;
    if prior["finding_retained"] == true {
        tx.commit()
            .await
            .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
        return Ok(prior);
    }
    let original = super::admission::load_in(&mut tx, parent)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let read = read_admission::load_in(&mut tx, id)
        .await?
        .ok_or(Failure("apify_read_intent_not_found"))?;
    let finding = super::read_finding::project(&original, &read, now)?
        .ok_or(Failure("apify_read_complete_pages_missing"))?;
    let at = crate::job_sources::access::time(&finding["observed_at"])?;
    if now - at > chrono::Duration::hours(24) {
        return Err(Failure("apify_read_finding_expired"));
    }
    let plan = settings.plan(
        original["source"].as_str().ok_or(ack())?,
        original["effective_query"].clone(),
        original["request"]["allow_paid"] == true,
        now,
    )?;
    if plan.context() != original["configuration_hash"].as_str().ok_or(ack())?
        || settings.credential_context()? != original["credential_context"].as_str().ok_or(ack())?
        || read["selected_build"]["id"] != plan.review.id
        || read["selected_build"]["schema_digest"] != plan.review.schema_digest
    {
        return Err(Failure("apify_read_configuration_changed"));
    }
    let monthly = super::budget::monthly_snapshot_in(&mut tx, &original["reservation"]).await?;
    let mut next = original.clone();
    next["state"] = json!("finding_retained");
    next["finding"] = finding;
    next["finding_hash"] = json!(crate::python_json::digest(&next["finding"]));
    next["read_finding"] = json!({"schema":1,"read_request_id":id,"finding_hash":next["finding_hash"],"original_journal_hash":read["original_journal_hash"]});
    let mut saved_read = read.clone();
    saved_read["state"] = json!("finding_retained");
    saved_read["finding_hash"] = next["finding_hash"].clone();
    if next.to_string().len() > 9437184 || saved_read.to_string().len() > 9437184 {
        return Err(Failure("apify_read_selected_limit"));
    }
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(super::admission::key(parent)).bind(&next).bind(&original).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&next) {
        return Err(ack());
    }
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(read_admission::key(id)).bind(&saved_read).bind(&read).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&saved_read) {
        return Err(ack());
    }
    let end = clock(&mut tx).await?;
    if end - at > chrono::Duration::hours(24) {
        return Err(Failure("apify_read_finding_expired"));
    }
    if super::admission::load_in(&mut tx, parent).await?.as_ref() != Some(&next)
        || read_admission::load_in(&mut tx, id).await?.as_ref() != Some(&saved_read)
        || super::budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await? != monthly
    {
        return Err(ack());
    }
    let out = read_admission::read_in(&mut tx, parent, id, end).await?;
    if out["finding_retained"] != true {
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
    Ok(out)
}
