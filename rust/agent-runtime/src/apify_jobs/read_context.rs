//! Pure original-checkpoint restoration and fixed GET targets; never a grant, reservation or transport.
use super::{
    evidence::{ActorIdentity, Run, VerifiedBuild},
    plan::{Plan, Target},
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::Value;
use uuid::Uuid;
pub struct ReadContext {
    plan: Plan,
    actor: ActorIdentity,
    run: Run,
    original_admitted: DateTime<Utc>,
    status_observed: bool,
}
pub struct ReadTarget {
    target: Target,
}
impl ReadTarget {
    pub fn method(&self) -> &str {
        self.target.method()
    }
    pub fn path(&self) -> &str {
        self.target.path()
    }
    pub fn query(&self) -> &[(String, String)] {
        self.target.query()
    }
}
fn invalid() -> Failure {
    Failure("apify_read_original_checkpoint_invalid")
}
impl ReadContext {
    /// The durable caller must separately validate the original SQL journal and reservation.
    /// Passing these pure checks cannot dispatch even one GET.
    pub fn from_retained(plan: Plan, journal: &Value, now: DateTime<Utc>) -> Result<Self> {
        let at = crate::job_sources::access::time(&journal["started_at"])?;
        let expires = crate::job_sources::access::time(&journal["expires_at"])?;
        if journal.to_string().len() > 9437184
            || journal["schema"] != 1
            || journal["request_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .is_none_or(|v| v.is_nil())
            || !matches!(
                journal["state"].as_str(),
                Some("operation_admitted" | "response_retained" | "failed")
            )
            || journal["start_intent"] != true
            || journal["start_attempted"] != true
            || journal["configuration_hash"] != plan.context()
            || journal["source"] != plan.portal()
            || journal["effective_query"] != plan.query
            || journal["selected_run_hash"] != crate::python_json::digest(&journal["selected_run"])
            || journal["reservation"]["provider"] != "apify"
            || journal["reservation"]["state"] != "run_attached"
            || journal["reservation"]["provider_run_id"] != journal["selected_run"]["id"]
            || expires != at + chrono::Duration::seconds(75)
        {
            return Err(invalid());
        }
        if now < expires {
            return Err(Failure("apify_read_original_still_active"));
        }
        if now - at > chrono::Duration::hours(24) {
            return Err(Failure("apify_read_original_expired"));
        }
        let actor = ActorIdentity::retained(&plan, &journal["selected_actor"])?;
        let run = Run::retained(&plan, &actor, &journal["selected_run"], at, now)?;
        if journal["selected_run"]["actId"] != actor.id() {
            return Err(invalid());
        }
        Ok(Self {
            plan,
            actor,
            run,
            original_admitted: at,
            status_observed: false,
        })
    }
    pub fn run_id(&self) -> &str {
        self.run.id()
    }
    pub fn selected_run(&self) -> Value {
        self.run.selected()
    }
    pub fn status_target(&self) -> Result<ReadTarget> {
        Ok(ReadTarget {
            target: self.plan.status(&self.run)?,
        })
    }
    pub fn accept_status(&mut self, body: &Value, now: DateTime<Utc>) -> Result<Value> {
        let run = Run::parse(
            &self.plan,
            &self.actor,
            body,
            Some(&self.run),
            self.original_admitted,
            now,
        )?;
        let selected = run.selected();
        self.run = run;
        self.status_observed = true;
        Ok(selected)
    }
    fn ready(&self) -> Result<()> {
        if !self.status_observed || !self.run.succeeded() {
            return Err(Failure("apify_read_succeeded_status_required"));
        }
        Ok(())
    }
    pub fn build_target(&self) -> Result<ReadTarget> {
        self.ready()?;
        Ok(ReadTarget {
            target: self.plan.build_metadata(&self.run)?,
        })
    }
    pub fn accept_build(&self, body: &Value) -> Result<VerifiedBuild> {
        self.ready()?;
        VerifiedBuild::parse(&self.plan, &self.run, body)
    }
    pub fn dataset_target(&self, build: &VerifiedBuild, offset: u64) -> Result<ReadTarget> {
        self.ready()?;
        Ok(ReadTarget {
            target: self.plan.dataset(&self.run, build, offset)?,
        })
    }
}
