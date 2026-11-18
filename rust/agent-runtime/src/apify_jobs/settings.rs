//! Private reviewed route selection. Source readiness is configuration evidence, not permission to execute.
use super::{
    money::Usd,
    plan::{BuildReview, Plan, Policy},
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
pub struct Settings {
    actors: Value,
    routes: Value,
    reviews: Value,
    monthly: Usd,
    cap: Usd,
    credential_context: Option<String>,
}
fn invalid() -> Failure {
    Failure("invalid_apify_execution_settings")
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let object = |key: &str| -> Result<Value> {
            match values.get(key) {
                None => Ok(json!({})),
                Some(raw) if raw.len() <= 524288 => serde_json::from_str::<Value>(raw)
                    .ok()
                    .filter(|v| v.as_object().is_some_and(|m| m.len() <= 100))
                    .ok_or_else(invalid),
                _ => Err(invalid()),
            }
        };
        let actors = object("APIFY_SOURCES")?;
        let routes = object("APIFY_SOURCE_ROUTES")?;
        let reviews = object("APIFY_BUILD_REVIEWS")?;
        if actors
            .as_object()
            .ok_or_else(invalid)?
            .values()
            .any(|v| !v.is_object())
            || routes.as_object().ok_or_else(invalid)?.values().any(|v| {
                v.as_array()
                    .is_none_or(|a| a.len() > 5 || a.iter().any(|v| !v.is_object()))
            })
            || reviews
                .as_object()
                .ok_or_else(invalid)?
                .values()
                .any(|v| BuildReview::parse(v).is_err())
        {
            return Err(invalid());
        }
        let monthly = Usd::parse(
            values
                .get("APIFY_MONTHLY_LIMIT_USD")
                .map(String::as_str)
                .unwrap_or("0"),
        )?;
        let cap = Usd::parse(
            values
                .get("APIFY_PER_RUN_CAP_USD")
                .map(String::as_str)
                .unwrap_or("0"),
        )?;
        if cap.micros() > 100_000_000 {
            return Err(invalid());
        }
        let credential_context = values
            .get("APIFY_API_TOKEN")
            .filter(|s| !s.trim().is_empty())
            .map(|s| format!("{:x}", Sha256::digest(s.as_bytes())));
        Ok(Self {
            actors,
            routes,
            reviews,
            monthly,
            cap,
            credential_context,
        })
    }
    pub fn monthly_cap(&self) -> Usd {
        self.monthly
    }
    pub fn per_run_cap(&self) -> Usd {
        self.cap
    }
    /// Saved prerequisites only; no Actor lookup, reservation or dispatch authority.
    pub fn preview(
        &self,
        portal: &str,
        query: Value,
        allow_paid: bool,
        now: DateTime<Utc>,
    ) -> Value {
        match self.plan(portal, query, allow_paid, now) {
            Ok(plan) => {
                let estimated = Usd::estimated_total(
                    &plan.actor["estimated_start_usd"],
                    &plan.actor["estimated_per_item_usd"],
                    plan.query["limit"].as_u64().unwrap_or(100),
                );
                json!({"ready":true,"blocker":null,"run_cap_usd":self.cap.decimal(),"monthly_limit_usd":self.monthly.decimal(),"estimated_usd":estimated.ok().and_then(|v|v.decimal().parse::<f64>().ok()),"accounting":"full_cap_reserved_until_independent_billing_reconciliation","provider_calls":0,"writes":0,"dispatch_authorized":false,"live_verified":false})
            }
            Err(e) => {
                json!({"ready":false,"blocker":e.0,"run_cap_usd":self.cap.decimal(),"monthly_limit_usd":self.monthly.decimal(),"estimated_usd":null,"provider_calls":0,"writes":0,"dispatch_authorized":false,"live_verified":false})
            }
        }
    }
    pub(super) fn credential_context(&self) -> Result<&str> {
        self.credential_context
            .as_deref()
            .ok_or(Failure("apify_local_token_not_configured"))
    }
    pub fn plan(
        &self,
        portal: &str,
        query: Value,
        allow_paid: bool,
        now: DateTime<Utc>,
    ) -> Result<Plan> {
        let present = self.credential_context.is_some();
        let candidates = if let Some(routes) = self
            .routes
            .get(portal)
            .and_then(Value::as_array)
            .filter(|a| !a.is_empty())
        {
            routes.clone()
        } else {
            vec![self.actors[portal].clone()]
        };
        // Select one reviewed route before original admission. Never fail over after possible dispatch.
        for actor in candidates {
            let review = if let Some(actor_id) = actor["actor_id"].as_str() {
                self.reviews
                    .get(format!("{portal}:{actor_id}"))
                    .or_else(|| self.reviews.get(portal))
            } else {
                None
            };
            let Some(review) = review else { continue };
            let review = BuildReview::parse(review)?;
            if let Ok(plan) = Plan::build(
                portal,
                actor,
                query.clone(),
                Policy {
                    monthly: self.monthly,
                    cap: self.cap,
                    allow_paid,
                    credential_present: present,
                    reviewed_build: review,
                },
                now,
            ) {
                return Ok(plan);
            }
        }
        if !allow_paid {
            return Err(Failure("apify_paid_opt_in_required"));
        }
        if !present {
            return Err(Failure("apify_local_token_not_configured"));
        }
        Err(Failure("apify_reviewed_execution_route_required"))
    }
}
