//! Closed official API targets. A plan has no token, durable reservation or dispatch grant.
use super::{
    evidence::{ActorIdentity, Run, VerifiedBuild},
    money::Usd,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
pub struct Plan {
    pub(super) portal: String,
    pub(super) actor: Value,
    pub(super) query: Value,
    pub(super) cap: Usd,
    pub(super) input: Value,
    pub(super) review: BuildReview,
    context: String,
}
pub struct BuildReview {
    pub(super) id: String,
    pub(super) schema_digest: String,
}
impl BuildReview {
    pub fn parse(value: &Value) -> Result<Self> {
        if value.as_object().is_none_or(|m| m.len() != 2) {
            return Err(Failure("apify_pinned_build_review_required"));
        }
        let id = value["build_id"]
            .as_str()
            .filter(|s| {
                !s.is_empty()
                    && s.len() <= 100
                    && s.bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            })
            .ok_or(Failure("apify_pinned_build_review_required"))?;
        let digest = value["schema_digest"]
            .as_str()
            .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or(Failure("apify_pinned_build_review_required"))?;
        Ok(Self {
            id: id.into(),
            schema_digest: digest.to_ascii_lowercase(),
        })
    }
}
pub struct Policy {
    pub monthly: Usd,
    pub cap: Usd,
    pub allow_paid: bool,
    pub credential_present: bool,
    pub reviewed_build: BuildReview,
}
pub struct Target {
    method: &'static str,
    path: String,
    query: Vec<(String, String)>,
    body: Option<Value>,
}
impl Target {
    pub fn method(&self) -> &'static str {
        self.method
    }
    pub fn path(&self) -> &str {
        &self.path
    }
    pub fn query(&self) -> &[(String, String)] {
        &self.query
    }
    pub fn body(&self) -> Option<&Value> {
        self.body.as_ref()
    }
}
impl Plan {
    pub fn build(
        portal: &str,
        actor: Value,
        query: Value,
        policy: Policy,
        now: DateTime<Utc>,
    ) -> Result<Self> {
        let Policy {
            monthly,
            cap,
            allow_paid,
            credential_present,
            reviewed_build,
        } = policy;
        if !crate::source_registry::APIFY_PORTALS.contains(&portal) {
            return Err(Failure("apify_portal_unknown"));
        }
        if !allow_paid {
            return Err(Failure("apify_paid_opt_in_required"));
        }
        if cap.micros() == 0 || cap.micros() > 100_000_000 || monthly < cap {
            return Err(Failure("apify_positive_bounded_budget_required"));
        }
        let actor = crate::apify_config::normalize(actor)?;
        let query = crate::job_sources::contract::query(query)?;
        if query["page"] != 1 {
            return Err(Failure("apify_first_page_only"));
        }
        let reviewed = crate::apify_config::preflight(
            actor.clone(),
            credential_present,
            monthly
                .decimal()
                .parse()
                .map_err(|_| Failure("invalid_apify_budget_configuration"))?,
            cap.decimal()
                .parse()
                .map_err(|_| Failure("invalid_apify_budget_configuration"))?,
            now,
        )?;
        if reviewed["configuration_review_ready"] != true {
            return Err(Failure("apify_review_prerequisites_required"));
        }
        let limit = query["limit"]
            .as_u64()
            .ok_or(Failure("invalid_apify_actor_configuration"))?;
        if Usd::estimated_total(
            &actor["estimated_start_usd"],
            &actor["estimated_per_item_usd"],
            limit,
        )? > cap
        {
            return Err(Failure("apify_estimate_exceeds_reserved_cap"));
        }
        let input = crate::apify_config::build_input(&actor, &query)?;
        crate::apify_config::execution_input_allowed(
            actor["actor_id"]
                .as_str()
                .ok_or(Failure("apify_actor_id_invalid"))?,
            &input,
        )?;
        let context = crate::python_json::digest(
            &json!({"schema":1,"portal":portal,"actor":actor,"query":query,"input":input,"cap_usd":cap.decimal(),"monthly_cap_usd":monthly.decimal(),"build_id":reviewed_build.id,"schema_digest":reviewed_build.schema_digest,"normalization":"selected_paid_job_claims_v1"}),
        );
        Ok(Self {
            portal: portal.into(),
            actor,
            query,
            cap,
            input,
            review: reviewed_build,
            context,
        })
    }
    pub fn portal(&self) -> &str {
        &self.portal
    }
    pub fn context(&self) -> &str {
        &self.context
    }
    pub fn cap(&self) -> Usd {
        self.cap
    }
    pub fn actor_metadata(&self) -> Result<Target> {
        Ok(Target {
            method: "GET",
            path: format!(
                "actors/{}",
                crate::apify_config::safe_actor(
                    self.actor["actor_id"]
                        .as_str()
                        .ok_or(Failure("apify_actor_id_invalid"))?
                )?
            ),
            query: vec![],
            body: None,
        })
    }
    pub fn reviewed_build(&self, identity: &ActorIdentity) -> Result<Target> {
        identity.matches(self)?;
        Ok(Target {
            method: "GET",
            path: format!("actor-builds/{}", self.review.id),
            query: vec![],
            body: None,
        })
    }
    pub fn start(&self, identity: &ActorIdentity, build: &VerifiedBuild) -> Result<Target> {
        identity.matches(self)?;
        build.pre_start(self, identity)?;
        Ok(Target {
            method: "POST",
            path: format!("actors/{}/runs", identity.id()),
            query: vec![
                (
                    "build".into(),
                    self.actor["build"]
                        .as_str()
                        .ok_or(Failure("invalid_apify_actor_configuration"))?
                        .into(),
                ),
                ("waitForFinish".into(), "15".into()),
                ("timeout".into(), "60".into()),
                ("maxTotalChargeUsd".into(), self.cap.decimal()),
                ("maxItems".into(), self.query["limit"].to_string()),
                ("restartOnError".into(), "false".into()),
            ],
            body: Some(self.input.clone()),
        })
    }
    pub fn status(&self, run: &Run) -> Result<Target> {
        run.matches(self)?;
        Ok(Target {
            method: "GET",
            path: format!("actor-runs/{}", run.id()),
            query: vec![("waitForFinish".into(), "10".into())],
            body: None,
        })
    }
    pub fn build_metadata(&self, run: &Run) -> Result<Target> {
        run.matches(self)?;
        Ok(Target {
            method: "GET",
            path: format!("actor-builds/{}", run.build_id()),
            query: vec![],
            body: None,
        })
    }
    pub fn abort(&self, run: &Run) -> Result<Target> {
        run.matches(self)?;
        Ok(Target {
            method: "POST",
            path: format!("actor-runs/{}/abort", run.id()),
            query: vec![("gracefully".into(), "false".into())],
            body: None,
        })
    }
    pub fn dataset(&self, run: &Run, build: &VerifiedBuild, offset: u64) -> Result<Target> {
        run.matches(self)?;
        build.matches(self, run)?;
        let max = self.query["limit"]
            .as_u64()
            .ok_or(Failure("invalid_apify_actor_configuration"))?;
        if !run.succeeded() || offset >= max || offset % 50 != 0 {
            return Err(Failure("apify_dataset_target_denied"));
        }
        Ok(Target {
            method: "GET",
            path: format!(
                "datasets/{}/items",
                run.dataset_id().ok_or(Failure("apify_dataset_not_bound"))?
            ),
            query: vec![
                ("offset".into(), offset.to_string()),
                ("limit".into(), 50.min(max - offset).to_string()),
                ("format".into(), "json".into()),
            ],
            body: None,
        })
    }
}
