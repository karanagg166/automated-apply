//! Selected original actor/run/build evidence. No URL following, provider calls or billing finality.
use super::{money::Usd, plan::Plan};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
fn invalid() -> Failure {
    Failure("apify_execution_evidence_invalid")
}
fn bounded(value: &Value) -> Result<()> {
    if value.to_string().len() > 1048576 {
        Err(Failure("apify_execution_response_limit"))
    } else {
        Ok(())
    }
}
fn id(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 100
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        })
        .ok_or_else(invalid)
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    v.as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|v| v.to_utc())
        .ok_or_else(invalid)
}
pub struct ActorIdentity {
    id: String,
    alias: String,
    context: String,
}
impl ActorIdentity {
    pub(super) fn retained(plan: &Plan, selected: &Value) -> Result<Self> {
        let alias = selected["alias"].as_str().ok_or_else(invalid)?;
        let (username, name) = alias.split_once('~').ok_or_else(invalid)?;
        let identity = Self::parse(
            plan,
            &json!({"data":{"id":selected["id"],"username":username,"name":name}}),
        )?;
        if identity.selected() != *selected {
            return Err(invalid());
        }
        Ok(identity)
    }
    pub fn parse(plan: &Plan, value: &Value) -> Result<Self> {
        bounded(value)?;
        let data = &value["data"];
        let actor = id(&data["id"])?;
        let username = id(&data["username"])?;
        let name = id(&data["name"])?;
        let alias = format!("{username}~{name}");
        if crate::apify_config::safe_actor(plan.actor["actor_id"].as_str().ok_or_else(invalid)?)?
            != alias
        {
            return Err(Failure("apify_actor_identity_mismatch"));
        }
        Ok(Self {
            id: actor.into(),
            alias,
            context: plan.context().into(),
        })
    }
    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn selected(&self) -> Value {
        json!({"id":self.id,"alias":self.alias,"identity_basis":"original_configured_actor_response"})
    }
    pub(super) fn matches(&self, plan: &Plan) -> Result<()> {
        if self.context != plan.context() {
            Err(Failure("apify_execution_context_changed"))
        } else {
            Ok(())
        }
    }
    fn same_actor(&self, v: &Value) -> bool {
        v.as_str().is_some_and(|s| s == self.id || s == self.alias)
    }
}
pub struct Run {
    id: String,
    actor: String,
    alias: String,
    build_id: String,
    build_number: String,
    status: String,
    dataset: Option<String>,
    started: DateTime<Utc>,
    finished: Option<DateTime<Utc>>,
    cost: Value,
    context: String,
    provider_cap: Usd,
    acknowledged_options: Value,
}
impl Run {
    pub fn parse(
        plan: &Plan,
        identity: &ActorIdentity,
        value: &Value,
        previous: Option<&Run>,
        admitted: DateTime<Utc>,
        now: DateTime<Utc>,
    ) -> Result<Self> {
        identity.matches(plan)?;
        bounded(value)?;
        let data = &value["data"];
        if !identity.same_actor(&data["actId"]) {
            return Err(Failure("apify_run_actor_mismatch"));
        }
        let id = id(&data["id"])?;
        let build_id = self::id(&data["buildId"])?;
        if build_id != plan.review.id {
            return Err(Failure("apify_run_build_mismatch"));
        }
        let build = data["buildNumber"]
            .as_str()
            .filter(|v| plan.actor["build"] == *v)
            .ok_or(Failure("apify_run_build_mismatch"))?;
        let status = data["status"]
            .as_str()
            .filter(|v| {
                matches!(
                    *v,
                    "READY"
                        | "QUEUED"
                        | "RUNNING"
                        | "SUCCEEDED"
                        | "FAILED"
                        | "TIMING-OUT"
                        | "TIMED-OUT"
                        | "ABORTING"
                        | "ABORTED"
                )
            })
            .ok_or_else(invalid)?;
        let started = time(&data["startedAt"])?;
        let finished = if data["finishedAt"].is_null() {
            None
        } else {
            Some(time(&data["finishedAt"])?)
        };
        if started < admitted - chrono::Duration::minutes(5)
            || started > now + chrono::Duration::minutes(5)
            || finished.is_some_and(|v| v < started || v > now + chrono::Duration::minutes(5))
        {
            return Err(invalid());
        }
        let dataset = if data["defaultDatasetId"].is_null() {
            None
        } else {
            Some(self::id(&data["defaultDatasetId"])?.to_owned())
        };
        let options = &data["options"];
        if options["restartOnError"] != false
            || options["timeoutSecs"]
                .as_u64()
                .is_none_or(|v| v == 0 || v > 60)
            || options["build"].as_str() != Some(build)
        {
            return Err(Failure("apify_run_options_not_acknowledged"));
        }
        let provider_cap = Usd::estimate(&options["maxTotalChargeUsd"])?;
        if provider_cap.micros() == 0 || provider_cap > plan.cap {
            return Err(Failure("apify_run_cap_not_acknowledged"));
        }
        if !options["maxItems"].is_null()
            && options["maxItems"]
                .as_u64()
                .is_none_or(|v| v == 0 || v > plan.query["limit"].as_u64().unwrap_or(0))
        {
            return Err(Failure("apify_run_item_option_not_acknowledged"));
        }
        let cost = data["usageTotalUsd"].clone();
        if !cost.is_null()
            && cost
                .as_f64()
                .is_none_or(|n| !n.is_finite() || !(0.0..=1e12).contains(&n))
        {
            return Err(invalid());
        }
        let out = Self {
            id: id.into(),
            actor: identity.id.clone(),
            alias: identity.alias.clone(),
            build_id: build_id.into(),
            build_number: build.into(),
            status: status.into(),
            dataset,
            started,
            finished,
            cost,
            context: plan.context().into(),
            provider_cap,
            acknowledged_options: json!({"build":options["build"],"timeoutSecs":options["timeoutSecs"],"restartOnError":false,"maxTotalChargeUsd":options["maxTotalChargeUsd"],"maxItems":options["maxItems"]}),
        };
        if status == "SUCCEEDED" && (out.dataset.is_none() || out.finished.is_none()) {
            return Err(invalid());
        }
        if let Some(previous) = previous {
            previous.matches(plan)?;
            if out.id != previous.id
                || out.actor != previous.actor
                || out.build_id != previous.build_id
                || out.build_number != previous.build_number
                || out.started != previous.started
                || out.provider_cap != previous.provider_cap
                || out.acknowledged_options != previous.acknowledged_options
                || previous.finished.is_some() && out.finished != previous.finished
                || previous.dataset.is_some() && out.dataset != previous.dataset
                || previous.terminal() && out.status != previous.status
            {
                return Err(Failure("apify_run_original_binding_changed"));
            }
        }
        Ok(out)
    }
    pub fn id(&self) -> &str {
        &self.id
    }
    /// Restore only selected original evidence. This does not acknowledge a new provider operation.
    pub(super) fn retained(
        plan: &Plan,
        identity: &ActorIdentity,
        selected: &Value,
        admitted: DateTime<Utc>,
        now: DateTime<Utc>,
    ) -> Result<Self> {
        let mut data = selected.clone();
        data["options"] = selected["acknowledged_options"].clone();
        let run = Self::parse(plan, identity, &json!({"data":data}), None, admitted, now)?;
        if run.selected() != *selected {
            return Err(invalid());
        }
        Ok(run)
    }
    pub fn build_id(&self) -> &str {
        &self.build_id
    }
    pub fn dataset_id(&self) -> Option<&str> {
        self.dataset.as_deref()
    }
    pub fn succeeded(&self) -> bool {
        self.status == "SUCCEEDED" && self.finished.is_some() && self.dataset.is_some()
    }
    pub fn terminal(&self) -> bool {
        matches!(
            self.status.as_str(),
            "SUCCEEDED" | "FAILED" | "TIMED-OUT" | "ABORTED"
        ) && self.finished.is_some()
    }
    pub(super) fn matches(&self, plan: &Plan) -> Result<()> {
        if self.context != plan.context() {
            Err(Failure("apify_execution_context_changed"))
        } else {
            Ok(())
        }
    }
    pub fn selected(&self) -> Value {
        json!({"id":self.id,"actId":self.actor,"buildId":self.build_id,"buildNumber":self.build_number,"status":self.status,"defaultDatasetId":self.dataset,"startedAt":self.started.to_rfc3339(),"finishedAt":self.finished.map(|v|v.to_rfc3339()),"usageTotalUsd":self.cost,"provider_cap_usd":self.provider_cap.decimal(),"acknowledged_options":self.acknowledged_options,"billing_final":false,"termination_observed":self.terminal(),"independent_termination_verified":false})
    }
}
pub struct VerifiedBuild {
    id: String,
    actor_id: String,
    run_id: Option<String>,
    context: String,
    schema: Option<Value>,
    digest: Option<String>,
    image: Option<String>,
}
impl VerifiedBuild {
    pub fn review(plan: &Plan, identity: &ActorIdentity, value: &Value) -> Result<Self> {
        identity.matches(plan)?;
        bounded(value)?;
        let data = &value["data"];
        if id(&data["id"])? != plan.review.id
            || !identity.same_actor(&data["actId"])
            || data["buildNumber"] != plan.actor["build"]
            || data["status"] != "SUCCEEDED"
        {
            return Err(Failure("apify_build_original_binding_changed"));
        }
        Self::from_payload(plan, None, identity.id(), value)
    }
    pub fn parse(plan: &Plan, run: &Run, value: &Value) -> Result<Self> {
        run.matches(plan)?;
        bounded(value)?;
        let data = &value["data"];
        if id(&data["id"])? != run.build_id
            || data["actId"]
                .as_str()
                .is_none_or(|s| s != run.actor && s != run.alias)
            || data["buildNumber"] != run.build_number
            || data["status"] != "SUCCEEDED"
        {
            return Err(Failure("apify_build_original_binding_changed"));
        }
        Self::from_payload(plan, Some(run.id.clone()), &run.actor, value)
    }
    fn from_payload(
        plan: &Plan,
        run_id: Option<String>,
        actor_id: &str,
        value: &Value,
    ) -> Result<Self> {
        let data = &value["data"];
        let image = match &data["imageDigest"] {
            Value::Null => None,
            Value::String(s) if s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()) => {
                Some(s.clone())
            }
            _ => return Err(invalid()),
        };
        let schema = match &data["inputSchema"] {
            Value::Null => None,
            Value::String(s) if s.len() <= 65536 => {
                Some(serde_json::from_str::<Value>(s).map_err(|_| invalid())?)
            }
            Value::Object(_) => Some(data["inputSchema"].clone()),
            _ => return Err(invalid()),
        };
        if schema
            .as_ref()
            .is_some_and(|v| !v.is_object() || v.to_string().len() > 65536)
        {
            return Err(invalid());
        }
        let digest = schema.as_ref().map(|v| {
            format!(
                "{:x}",
                sha2::Sha256::digest(crate::python_json::serialize(v, false, true).as_bytes())
            )
        });
        let result = Self {
            id: plan.review.id.clone(),
            actor_id: actor_id.into(),
            run_id,
            context: plan.context().into(),
            schema,
            digest,
            image,
        };
        result.reviewed_input_matches(&plan.review.schema_digest, &plan.input)?;
        Ok(result)
    }
    pub(super) fn matches(&self, plan: &Plan, run: &Run) -> Result<()> {
        if self.context != plan.context()
            || self.id != run.build_id
            || self.actor_id != run.actor
            || self.run_id.as_deref().is_some_and(|id| id != run.id)
        {
            Err(Failure("apify_build_original_binding_changed"))
        } else {
            Ok(())
        }
    }
    pub(super) fn pre_start(&self, plan: &Plan, identity: &ActorIdentity) -> Result<()> {
        if self.context != plan.context()
            || self.id != plan.review.id
            || self.run_id.is_some()
            || self.actor_id != identity.id()
        {
            return Err(Failure("apify_build_original_binding_changed"));
        }
        self.reviewed_input_matches(&plan.review.schema_digest, &plan.input)
    }
    pub fn selected(&self) -> Value {
        json!({"id":self.id,"run_id":self.run_id,"schema_digest":self.digest,"image_digest":self.image,"input_schema_available":self.schema.is_some(),"live_verified":false})
    }
    pub fn reviewed_input_matches(&self, expected: &str, input: &Value) -> Result<()> {
        if self.digest.as_deref() != Some(expected) {
            return Err(Failure("apify_reviewed_schema_changed"));
        }
        let schema = self
            .schema
            .as_ref()
            .ok_or(Failure("apify_reviewed_schema_missing"))?;
        fn refs(value: &Value) -> bool {
            match value {
                Value::Object(m) => {
                    ["$ref", "$dynamicRef", "$recursiveRef", "$vocabulary"]
                        .iter()
                        .any(|k| m.contains_key(*k))
                        || m.values().any(refs)
                }
                Value::Array(a) => a.iter().any(refs),
                _ => false,
            }
        }
        // Never allow the schema validator to fetch references or execute defaults.
        if refs(schema) {
            return Err(Failure("apify_schema_reference_not_supported"));
        }
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(schema)
            .map_err(|_| invalid())?;
        if !validator.is_valid(input) {
            return Err(Failure("apify_reviewed_input_schema_mismatch"));
        }
        Ok(())
    }
}
use sha2::Digest;
