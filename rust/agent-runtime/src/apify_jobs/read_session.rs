//! One consumed read claim, durable GET-only operations and selected checkpoints. No paid start/abort path.
use super::{
    admission, budget,
    read_admission::{self, Claim},
    read_context::{ReadContext, ReadTarget},
    settings::Settings,
    transport::{Client, Outcome, Permit},
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{PgConnection, Postgres, Transaction};
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
pub(super) struct Session {
    claim: Claim,
    context: ReadContext,
    pending: bool,
}
impl Session {
    pub(super) fn original(mut claim: Claim) -> Result<Self> {
        let context = claim
            .context
            .take()
            .ok_or(Failure("apify_read_original_grant_missing"))?;
        Ok(Self {
            claim,
            context,
            pending: false,
        })
    }
    pub(super) fn context(&self) -> &ReadContext {
        &self.context
    }
    async fn admit_operation(
        &mut self,
        c: &mut PgConnection,
        client: &Client,
        settings: &Settings,
        kind: &'static str,
        target: ReadTarget,
    ) -> Result<Permit> {
        let sequence = self.claim.journal["operation"]["sequence"]
            .as_u64()
            .unwrap_or(0)
            + 1;
        if self.pending
            || !self.claim.journal["failure_codes"]
                .as_array()
                .is_some_and(|a| a.is_empty())
            || target.method() != "GET"
            || !matches!(
                (sequence, kind),
                (1, "status") | (2, "run_build") | (3 | 4, "dataset")
            )
            || !client.matches(
                self.claim.original["credential_context"]
                    .as_str()
                    .unwrap_or(""),
            )
        {
            return Err(Failure("apify_read_operation_sequence_conflict"));
        }
        if kind == "dataset"
            && !target.query().contains(&(
                "offset".into(),
                if sequence == 3 { "0" } else { "50" }.into(),
            ))
        {
            return Err(Failure("apify_read_operation_sequence_conflict"));
        }
        let target = target.into_target();
        let mut tx = admission::transaction(c).await?;
        read_admission::assert_original_in(&mut tx, settings, &self.claim).await?;
        let at = clock(&mut tx).await?;
        let mut next = self.claim.journal.clone();
        next["state"] = json!("operation_admitted");
        next["operation"] = json!({"sequence":sequence,"kind":kind,"state":"admitted","admitted_at":at.to_rfc3339(),"target_hash":crate::python_json::digest(&json!({"method":target.method(),"path":target.path(),"query":target.query(),"body":null}))});
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(read_admission::key(self.claim.id)).bind(&next).bind(&self.claim.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next) {
            return Err(ack());
        }
        let end = clock(&mut tx).await?;
        read_admission::verify_saved_in(
            &mut tx,
            &self.claim,
            &next,
            &self.claim.original,
            &self.claim.monthly,
            end,
        )
        .await?;
        if end >= self.claim.expires {
            return Err(Failure("apify_read_operation_expired"));
        }
        let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(end).fetch_one(&mut *tx).await.map_err(db)?;
        if cooling {
            return Err(Failure("apify_execution_cooling_down"));
        }
        tx.commit()
            .await
            .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
        self.claim.journal = next;
        self.pending = true;
        Ok(Permit {
            request: self.claim.id,
            invocation: self.claim.invocation,
            sequence,
            target,
            credential_context: self.claim.original["credential_context"]
                .as_str()
                .ok_or(ack())?
                .into(),
            expires: self.claim.expires,
            read_only: true,
        })
    }
    async fn retain(
        &mut self,
        c: &mut PgConnection,
        outcome: &Outcome,
        selected: Option<Value>,
        parse_error: Option<&'static str>,
    ) -> Result<()> {
        if !self.pending
            || outcome.request != self.claim.id
            || outcome.invocation != self.claim.invocation
            || self.claim.journal["operation"]["sequence"] != json!(outcome.sequence)
        {
            return Err(Failure("apify_read_operation_sequence_conflict"));
        }
        let mut tx = admission::transaction(c).await?;
        let at = clock(&mut tx).await?;
        read_admission::verify_saved_in(
            &mut tx,
            &self.claim,
            &self.claim.journal,
            &self.claim.original,
            &self.claim.monthly,
            at,
        )
        .await?;
        let error = outcome.code.or(parse_error);
        let mut next = self.claim.journal.clone();
        let mut original = self.claim.original.clone();
        next["state"] = json!(if error.is_some() {
            "failed"
        } else {
            "response_retained"
        });
        next["operation"]["state"] = json!("retained");
        next["operation"]["attempted"] = json!(outcome.attempted);
        next["operation"]["response_observed"] = json!(outcome.response_observed);
        next["operation"]["failure_code"] = json!(error);
        next["http_attempts"] =
            json!(next["http_attempts"].as_u64().unwrap_or(0) + u64::from(outcome.attempted));
        next["http_responses"] = json!(
            next["http_responses"].as_u64().unwrap_or(0) + u64::from(outcome.response_observed)
        );
        let total = next["decoded_bytes"].as_u64().unwrap_or(0) + outcome.bytes as u64;
        if total > 4194304 {
            return Err(Failure("apify_read_aggregate_byte_limit"));
        }
        next["decoded_bytes"] = json!(total);
        if let Some(code) = error {
            let errors = next["failure_codes"].as_array_mut().ok_or(ack())?;
            if !errors.contains(&json!(code)) {
                errors.push(json!(code));
            }
            if errors.len() > 30 {
                return Err(Failure("apify_read_selected_limit"));
            }
        }
        if let Some(selected) = selected {
            if selected.to_string().len() > 4194304 {
                return Err(Failure("apify_read_selected_limit"));
            }
            next["operation"]["selected_hash"] = json!(crate::python_json::digest(&selected));
            match next["operation"]["kind"].as_str() {
                Some("status") => {
                    if selected["id"] != original["selected_run"]["id"]
                        || selected["id"] != original["reservation"]["provider_run_id"]
                    {
                        return Err(Failure("apify_run_original_binding_changed"));
                    }
                    original["selected_run"] = selected.clone();
                    original["selected_run_hash"] = json!(crate::python_json::digest(&selected));
                    original["read_observation"] = json!({"schema":1,"read_request_id":self.claim.id,"sequence":outcome.sequence,"selected_run_hash":original["selected_run_hash"],"observed_at":at.to_rfc3339(),"independent_termination_verified":false,"billing_final":false});
                    next["selected_run_hash"] = json!(crate::python_json::digest(&selected));
                    next["selected_run"] = selected;
                }
                Some("run_build") => {
                    next["selected_build_hash"] = json!(crate::python_json::digest(&selected));
                    next["selected_build"] = selected;
                }
                Some("dataset") => {
                    if next["selected_pages"].is_null() {
                        next["selected_pages"] = json!([]);
                    }
                    let pages = next["selected_pages"].as_array_mut().ok_or(ack())?;
                    if pages.len() >= 2 || selected["offset"] != json!(pages.len() * 50) {
                        return Err(ack());
                    }
                    pages.push(
                        json!({"hash":crate::python_json::digest(&selected),"page":selected}),
                    );
                }
                _ => return Err(Failure("apify_read_operation_sequence_conflict")),
            }
        }
        let monthly = if let Some(until) = outcome.cooldown {
            budget::cooldown_in(
                &mut tx,
                &original["reservation"],
                &self.claim.monthly,
                until,
            )
            .await?
        } else {
            self.claim.monthly.clone()
        };
        if original != self.claim.original {
            let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(self.claim.parent)).bind(&original).bind(&self.claim.original).fetch_optional(&mut *tx).await.map_err(db)?;
            if saved.as_ref() != Some(&original) {
                return Err(ack());
            }
        }
        if next.to_string().len() > 9437184 || original.to_string().len() > 9437184 {
            return Err(Failure("apify_read_selected_limit"));
        }
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(read_admission::key(self.claim.id)).bind(&next).bind(&self.claim.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next) {
            return Err(ack());
        }
        let end = clock(&mut tx).await?;
        read_admission::verify_saved_in(&mut tx, &self.claim, &next, &original, &monthly, end)
            .await?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
        self.claim.journal = next;
        self.claim.original = original;
        self.claim.monthly = monthly;
        self.pending = false;
        Ok(())
    }
    pub(super) async fn exchange<T>(
        &mut self,
        c: &mut PgConnection,
        client: &Client,
        settings: &Settings,
        kind: &'static str,
        target: ReadTarget,
        parse: impl FnOnce(&mut ReadContext, &Value) -> Result<(T, Value)>,
    ) -> Result<T> {
        let permit = self
            .admit_operation(c, client, settings, kind, target)
            .await?;
        let outcome = client.execute(permit).await;
        let parsed = outcome
            .body
            .as_ref()
            .map(|body| parse(&mut self.context, body));
        let (selected, code) = match &parsed {
            Some(Ok((_, v))) => (Some(v.clone()), None),
            Some(Err(e)) => (None, Some(e.0)),
            None => (None, None),
        };
        self.retain(c, &outcome, selected, code).await?;
        match parsed {
            Some(Ok((v, _))) => Ok(v),
            Some(Err(e)) => Err(e),
            None => Err(Failure(
                outcome
                    .code
                    .unwrap_or("apify_execution_transport_unconfirmed"),
            )),
        }
    }
}
