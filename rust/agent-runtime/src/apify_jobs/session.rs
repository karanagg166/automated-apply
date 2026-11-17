//! Durable one-operation-at-a-time original invocation. No transaction spans HTTP.
use super::{
    admission::{self, Claim, Grant},
    budget,
    plan::{Plan, Target},
    settings::Settings,
    transport::{Client, Outcome, Permit},
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::PgConnection;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_execution_database_error")
}
fn ack() -> Failure {
    Failure("apify_execution_write_ack_failed")
}
pub(super) struct Session {
    grant: Grant,
    journal: Value,
    pending: bool,
}
impl Session {
    pub(super) fn original(mut claim: Claim) -> Result<Self> {
        let grant = claim
            .grant
            .take()
            .ok_or(Failure("apify_original_grant_missing"))?;
        Ok(Self {
            grant,
            journal: claim.journal,
            pending: false,
        })
    }
    pub(super) fn plan(&self) -> &Plan {
        &self.grant.plan
    }
    pub(super) fn started(&self) -> Result<DateTime<Utc>> {
        crate::job_sources::access::time(&self.journal["started_at"])
    }
    pub(super) async fn note_failure(
        &mut self,
        c: &mut PgConnection,
        error: Failure,
    ) -> Result<()> {
        if self.pending {
            return Ok(());
        }
        let mut errors = self
            .journal
            .get("failure_codes")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if errors.contains(&json!(error.0)) {
            return Ok(());
        }
        errors.push(json!(error.0));
        if errors.len() > 30 {
            return Err(Failure("apify_execution_selected_limit"));
        }
        let mut tx = admission::transaction(c).await?;
        let mut next = self.journal.clone();
        next["failure_codes"] = json!(errors);
        next["state"] = json!("failed");
        let monthly = budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await?;
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(self.grant.id)).bind(&next).bind(&self.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next)
            || admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&next)
            || budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await? != monthly
        {
            return Err(ack());
        }
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        admission::project_in(&mut tx, &next, self.grant.id, now).await?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
        self.journal = next;
        Ok(())
    }
    pub(super) async fn finish_finding(
        &mut self,
        c: &mut PgConnection,
        finding: Value,
    ) -> Result<()> {
        if self.pending
            || self.journal["selected_run"]["status"] != "SUCCEEDED"
            || self.journal["operation"]["kind"] != "dataset"
            || self.journal["operation"]["state"] != "retained"
        {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        let mut tx = admission::transaction(c).await?;
        if admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&self.journal) {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        let finding = super::finding::project(
            &finding,
            self.grant.plan.portal(),
            self.grant.plan.query["limit"]
                .as_u64()
                .ok_or(Failure("invalid_apify_original_intent"))?,
            now,
        )?;
        let monthly = budget::monthly_snapshot_in(&mut tx, &self.journal["reservation"]).await?;
        let mut next = self.journal.clone();
        next["state"] = json!("finding_retained");
        next["finding_hash"] = json!(crate::python_json::digest(&finding));
        next["finding"] = finding;
        if next.to_string().len() > 9437184 {
            return Err(Failure("apify_execution_selected_limit"));
        }
        if next.to_string().len() > 9437184 {
            return Err(Failure("apify_execution_selected_limit"));
        }
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(self.grant.id)).bind(&next).bind(&self.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next)
            || admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&next)
            || budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await? != monthly
        {
            return Err(ack());
        }
        admission::project_in(&mut tx, &next, self.grant.id, now).await?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
        self.journal = next;
        Ok(())
    }
    async fn admit_operation(
        &mut self,
        c: &mut PgConnection,
        client: &Client,
        settings: &Settings,
        kind: &'static str,
        target: Target,
    ) -> Result<Permit> {
        if self.pending
            || !matches!(
                kind,
                "actor" | "reviewed_build" | "start" | "status" | "run_build" | "dataset" | "abort"
            )
        {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        if kind == "start" && self.journal["start_intent"] == true
            || kind == "abort" && self.journal["abort_intent"] == true
        {
            return Err(Failure("apify_original_operation_already_admitted"));
        }
        let sequence = self.journal["operation"]["sequence"].as_u64().unwrap_or(0) + 1;
        if sequence > 12 {
            return Err(Failure("apify_original_operation_limit"));
        }
        if !client.matches(self.journal["credential_context"].as_str().unwrap_or("")) {
            return Err(Failure("apify_execution_context_changed"));
        }
        let mut tx = admission::transaction(c).await?;
        if admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&self.journal) {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        let at: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        if at >= self.grant.expires {
            return Err(Failure("apify_original_operation_expired_or_changed"));
        }
        admission::project_in(&mut tx, &self.journal, self.grant.id, at).await?;
        if kind == "start" {
            let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(at).fetch_one(&mut *tx).await.map_err(db)?;
            if cooling {
                return Err(Failure("apify_execution_cooling_down"));
            }
        }
        let profile = if self.journal["start_intent"] != true {
            Some(
                crate::startup_catalog::detail::profile_in(
                    &mut tx,
                    self.journal["request"]["use_profile"] == true,
                )
                .await?,
            )
        } else {
            None
        };
        if let Some(profile) = &profile {
            if crate::job_sources::scope::profile_pin(profile.as_ref())?
                != self.journal["profile_pin"]
            {
                return Err(Failure("apify_execution_profile_changed"));
            }
            let plan = settings.plan(
                self.grant.plan.portal(),
                self.journal["effective_query"].clone(),
                true,
                at,
            )?;
            if plan.context() != self.grant.plan.context()
                || settings.credential_context()?
                    != self.journal["credential_context"].as_str().unwrap_or("")
            {
                return Err(Failure("apify_execution_context_changed"));
            }
        }
        let monthly = budget::monthly_snapshot_in(&mut tx, &self.journal["reservation"]).await?;
        let mut next = self.journal.clone();
        next["state"] = json!("operation_admitted");
        next["operation"] = json!({"sequence":sequence,"kind":kind,"state":"admitted","target_hash":crate::python_json::digest(&json!({"method":target.method(),"path":target.path(),"query":target.query(),"body":target.body()})),"admitted_at":at.to_rfc3339()});
        for key in ["http_attempts", "http_responses", "decoded_bytes"] {
            if next[key].is_null() {
                next[key] = json!(0)
            }
        }
        if kind == "start" {
            next["start_intent"] = json!(true)
        }
        if kind == "abort" {
            next["abort_intent"] = json!(true)
        }
        if next.to_string().len() > 9437184 {
            return Err(Failure("apify_execution_selected_limit"));
        }
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(self.grant.id)).bind(&next).bind(&self.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next)
            || admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&next)
            || budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await? != monthly
        {
            return Err(ack());
        }
        if let Some(profile) = profile {
            let reloaded = crate::startup_catalog::detail::profile_in(
                &mut tx,
                next["request"]["use_profile"] == true,
            )
            .await?;
            if crate::job_sources::scope::profile_pin(reloaded.as_ref())?
                != crate::job_sources::scope::profile_pin(profile.as_ref())?
            {
                return Err(ack());
            }
        }
        let end: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        admission::project_in(&mut tx, &next, self.grant.id, end).await?;
        if kind == "start" {
            let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(end).fetch_one(&mut *tx).await.map_err(db)?;
            if cooling {
                return Err(ack());
            }
        }
        if end >= self.grant.expires {
            return Err(Failure("apify_original_operation_expired_or_changed"));
        }
        tx.commit()
            .await
            .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
        self.journal = next;
        self.pending = true;
        Ok(Permit {
            read_only: false,
            request: self.grant.id,
            invocation: self.grant.invocation,
            sequence,
            target,
            credential_context: self.journal["credential_context"]
                .as_str()
                .ok_or(Failure("apify_execution_context_changed"))?
                .into(),
            expires: self.grant.expires,
        })
    }
    async fn retain(
        &mut self,
        c: &mut PgConnection,
        outcome: &Outcome,
        selected: Option<Value>,
        parse_code: Option<&'static str>,
    ) -> Result<()> {
        if !self.pending
            || outcome.request != self.grant.id
            || outcome.invocation != self.grant.invocation
            || self.journal["operation"]["sequence"] != json!(outcome.sequence)
        {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        let mut tx = admission::transaction(c).await?;
        if admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&self.journal) {
            return Err(Failure("apify_original_operation_sequence_conflict"));
        }
        let mut next = self.journal.clone();
        let monthly = budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await?;
        let kind = next["operation"]["kind"]
            .as_str()
            .ok_or(Failure("invalid_apify_original_intent"))?
            .to_owned();
        let error = outcome.code.or(parse_code);
        if let Some(code) = error {
            let mut errors = next
                .get("failure_codes")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if !errors.contains(&json!(code)) {
                errors.push(json!(code));
            }
            if errors.len() > 30 {
                return Err(Failure("apify_execution_selected_limit"));
            }
            next["failure_codes"] = json!(errors);
        }
        next["state"] = json!(if error.is_some() {
            "failed"
        } else {
            "response_retained"
        });
        next["operation"]["state"] = json!("retained");
        next["operation"]["attempted"] = json!(outcome.attempted);
        next["operation"]["response_observed"] = json!(outcome.response_observed);
        next["operation"]["failure_code"] = json!(error);
        if kind == "start" {
            next["start_attempted"] = json!(outcome.attempted)
        }
        next["http_attempts"] =
            json!(next["http_attempts"].as_u64().unwrap_or(0) + u64::from(outcome.attempted));
        next["http_responses"] = json!(
            next["http_responses"].as_u64().unwrap_or(0) + u64::from(outcome.response_observed)
        );
        let total = next["decoded_bytes"].as_u64().unwrap_or(0) + outcome.bytes as u64;
        if total > 8388608 {
            return Err(Failure("apify_execution_aggregate_byte_limit"));
        }
        next["decoded_bytes"] = json!(total);
        if let Some(selected) = selected {
            if selected.to_string().len() > 8388608 {
                return Err(Failure("apify_execution_selected_limit"));
            }
            next["operation"]["selected_hash"] = json!(crate::python_json::digest(&selected));
            match kind.as_str() {
                "actor" => next["selected_actor"] = selected,
                "reviewed_build" | "run_build" => next["selected_build"] = selected,
                "start" | "status" | "abort" => {
                    next["reservation"] =
                        budget::attach_in(&mut tx, self.grant.id, &next["reservation"], &selected)
                            .await?;
                    next["selected_run"] = selected;
                    next["selected_run_hash"] =
                        json!(crate::python_json::digest(&next["selected_run"]));
                }
                "dataset" => {
                    next["selected_page"] = selected;
                }
                _ => return Err(Failure("invalid_apify_original_intent")),
            }
        }
        let expected_monthly = if let Some(until) = outcome.cooldown {
            let value:Value=sqlx::query_scalar("UPDATE discovery_monthly_budgets AS b SET cooldown_until=GREATEST(cooldown_until,$2) WHERE provider='apify' AND month=$1 RETURNING to_jsonb(b)").bind(next["reservation"]["month"].as_str()).bind(until).fetch_one(&mut *tx).await.map_err(db)?;
            let mut expected = monthly.0.clone();
            let saved_time:Value=sqlx::query_scalar("SELECT to_jsonb(GREATEST(($1::jsonb->>'cooldown_until')::timestamptz,$2::timestamptz))").bind(&monthly.0).bind(until).fetch_one(&mut *tx).await.map_err(db)?;
            expected["cooldown_until"] = saved_time;
            if value != expected {
                return Err(ack());
            }
            (expected, monthly.1)
        } else {
            monthly
        };
        if next.to_string().len() > 9437184 {
            return Err(Failure("apify_execution_selected_limit"));
        }
        let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(self.grant.id)).bind(&next).bind(&self.journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next)
            || admission::load_in(&mut tx, self.grant.id).await?.as_ref() != Some(&next)
            || budget::monthly_snapshot_in(&mut tx, &next["reservation"]).await? != expected_monthly
        {
            return Err(ack());
        }
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        admission::project_in(&mut tx, &next, self.grant.id, now).await?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
        self.journal = next;
        self.pending = false;
        Ok(())
    }
    pub(super) async fn exchange<T>(
        &mut self,
        c: &mut PgConnection,
        client: &Client,
        settings: &Settings,
        kind: &'static str,
        target: Target,
        parse: impl FnOnce(&Plan, &Value) -> Result<(T, Value)>,
    ) -> Result<T> {
        let permit = self
            .admit_operation(c, client, settings, kind, target)
            .await?;
        let outcome = client.execute(permit).await;
        let parsed = if let Some(body) = &outcome.body {
            parse(&self.grant.plan, body)
        } else {
            Err(Failure(
                outcome
                    .code
                    .unwrap_or("apify_execution_transport_unconfirmed"),
            ))
        };
        match parsed {
            Ok((typed, selected)) => {
                self.retain(c, &outcome, Some(selected), None).await?;
                Ok(typed)
            }
            Err(error) => {
                self.retain(c, &outcome, None, Some(error.0)).await?;
                Err(error)
            }
        }
    }
}
