//! Owner-selected inference roles, pinned per run; never supplied by a model or website.
use crate::{
    Failure, Result,
    contracts::{Limits, Role},
    provider::CohereModel,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "provider", rename_all = "snake_case", deny_unknown_fields)]
pub enum Policy {
    Deterministic {},
    Cohere { model: String, roles: Vec<Role> },
}
#[derive(Clone)]
pub struct Models {
    pub(crate) client: CohereModel,
    pub(crate) roles: Vec<Role>,
}
impl Models {
    pub(crate) fn from_values(
        values: &BTreeMap<String, String>,
        fixture: bool,
    ) -> Result<Option<Self>> {
        let client = CohereModel::runtime(values, fixture)?;
        let Some(client) = client else {
            if values.contains_key("RUST_AGENT_MODEL_ROLES") {
                return Err(Failure("model_roles_require_provider"));
            }
            return Ok(None);
        };
        let mut roles = Vec::new();
        for name in values
            .get("RUST_AGENT_MODEL_ROLES")
            .map(String::as_str)
            .unwrap_or("review")
            .split(',')
        {
            let role = match name.trim() {
                "discovery" => Role::Discovery,
                "review" => Role::Review,
                _ => return Err(Failure("invalid_model_roles")),
            };
            if roles.contains(&role) {
                return Err(Failure("invalid_model_roles"));
            }
            roles.push(role);
        }
        if !roles.contains(&Role::Review) {
            return Err(Failure("review_model_role_required"));
        }
        if roles.len() == 2 {
            roles = vec![Role::Discovery, Role::Review];
        }
        Ok(Some(Self { client, roles }))
    }
    pub fn policy(&self) -> Policy {
        Policy::Cohere {
            model: self.client.name().into(),
            roles: self.roles.clone(),
        }
    }
    pub(crate) fn matches(&self, policy: &Policy) -> bool {
        match policy {
            Policy::Deterministic {} => true,
            Policy::Cohere { model, roles } => {
                model == self.client.name()
                    && !roles.is_empty()
                    && roles.contains(&Role::Review)
                    && roles.iter().all(|role| self.roles.contains(role))
                    && roles
                        .iter()
                        .enumerate()
                        .all(|(i, r)| !roles[..i].contains(r))
            }
        }
    }
}
impl Policy {
    pub fn roles(&self) -> &[Role] {
        match self {
            Self::Deterministic {} => &[],
            Self::Cohere { roles, .. } => roles,
        }
    }
    pub fn validate(&self) -> Result<()> {
        if let Self::Cohere { model, roles } = self
            && (!matches!(
                model.as_str(),
                "command-a-plus-05-2026" | "command-a-03-2025"
            ) || roles.is_empty()
                || !roles.contains(&Role::Review)
                || roles
                    .iter()
                    .any(|role| !matches!(role, Role::Discovery | Role::Review))
                || roles
                    .iter()
                    .enumerate()
                    .any(|(i, r)| roles[..i].contains(r)))
        {
            return Err(Failure("invalid_model_policy"));
        }
        Ok(())
    }
    pub fn recommended_limits(&self) -> Limits {
        let mut limits = Limits {
            human_review: true,
            decision_calls: 32,
            ..Limits::default()
        };
        if let Self::Cohere { roles, .. } = self {
            limits.tokens = 16000;
            if roles.len() > 1 {
                limits.replans = 1;
                limits.model_calls = 4;
                limits.max_input_tokens = 3800;
            } else {
                limits.model_calls = 3;
                limits.max_input_tokens = 5000;
            }
        }
        limits
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{planner::HybridPlanner, runner::Model};
    fn values() -> BTreeMap<String, String> {
        [
            ("RUST_AGENT_REVIEW_MODEL", "cohere"),
            ("COHERE_ENABLED", "true"),
            ("COHERE_EVALUATION_KEY_CONFIRMED", "true"),
            ("COHERE_OWNER_TEXT_AUTHORIZED", "true"),
            ("COHERE_CANDIDATE_DATA_AUTHORIZED", "true"),
            ("COHERE_API_KEY", "fictional-model-policy-key"),
            (
                "RUST_COHERE_FIXTURE_ENDPOINT",
                "http://127.0.0.1:12123/v2/chat",
            ),
        ]
        .into_iter()
        .map(|(k, v)| (k.into(), v.into()))
        .collect()
    }
    #[test]
    fn configured_roles_require_consents_and_total_budgets_fit_the_bound() {
        let mut v = values();
        let single = Models::from_values(&v, true).unwrap().unwrap();
        assert_eq!(single.roles, vec![Role::Review]);
        v.insert("RUST_AGENT_MODEL_ROLES".into(), "review, discovery".into());
        let models = Models::from_values(&v, true).unwrap().unwrap();
        assert_eq!(models.roles, vec![Role::Discovery, Role::Review]);
        let policy = models.policy();
        let limits = policy.recommended_limits();
        limits.validate().unwrap();
        assert_eq!(limits.replans, 1);
        assert_eq!(limits.model_calls, 4);
        assert!(
            u32::from(limits.model_calls) * (limits.max_input_tokens + limits.max_output_tokens)
                <= limits.tokens
        );
        for bad in [
            "execution",
            "discovery",
            "review,review",
            "review,unknown",
            "",
            ",review",
            "discovery,review,",
        ] {
            v.insert("RUST_AGENT_MODEL_ROLES".into(), bad.into());
            assert!(Models::from_values(&v, true).is_err());
        }
        v.insert("RUST_AGENT_MODEL_ROLES".into(), "discovery,review".into());
        v.remove("COHERE_CANDIDATE_DATA_AUTHORIZED");
        assert!(Models::from_values(&v, true).is_err());
        assert!(
            Models::from_values(
                &BTreeMap::from([("RUST_AGENT_MODEL_ROLES".into(), "review".into())]),
                true
            )
            .is_err()
        );
    }
    #[test]
    fn pinned_policies_cannot_be_upgraded_downgraded_or_switched_silently() {
        let mut v = values();
        v.insert("RUST_AGENT_MODEL_ROLES".into(), "discovery,review".into());
        let models = Models::from_values(&v, true).unwrap().unwrap();
        let policy = models.policy();
        let pinned = HybridPlanner::for_run(Some(&policy), Some(&models), false).unwrap();
        assert_eq!(pinned.roles, vec![Role::Discovery, Role::Review]);
        assert!(HybridPlanner::for_run(Some(&policy), None, false).is_err());
        v.insert("RUST_AGENT_MODEL_ROLES".into(), "review".into());
        let restricted = Models::from_values(&v, true).unwrap().unwrap();
        assert!(HybridPlanner::for_run(Some(&policy), Some(&restricted), false).is_err());
        let deterministic =
            HybridPlanner::for_run(Some(&Policy::Deterministic {}), Some(&models), false).unwrap();
        assert!(deterministic.roles.is_empty());
        assert!(!deterministic.inference_required(Role::Discovery, &[]));
        let legacy = HybridPlanner::for_run(None, Some(&models), false).unwrap();
        assert_eq!(legacy.roles, vec![Role::Review]);
        let changed = Policy::Cohere {
            model: "command-a-03-2025".into(),
            roles: vec![Role::Review],
        };
        assert!(HybridPlanner::for_run(Some(&changed), Some(&models), false).is_err());
        assert!(
            serde_json::from_value::<Policy>(
                serde_json::json!({"provider":"deterministic","authority":true})
            )
            .is_err()
        );
    }
}
