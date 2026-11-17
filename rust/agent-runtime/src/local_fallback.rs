//! One opt-in local fallback under an original transport deadline. Ledger work is never cancelled here.
use crate::{Failure, Result, configuration::boolean};
use std::{collections::BTreeMap, time::Duration};
use tokio::time::Instant;
pub(crate) struct Policy {
    pub(crate) enabled: bool,
    pub(crate) timeout: Duration,
}
impl Policy {
    pub(crate) fn from_values(values: &BTreeMap<String, String>, primary: &str) -> Result<Self> {
        let enabled = boolean(values, "LLM_LOCAL_FALLBACK_ENABLED", false)?
            && primary != "ollama"
            && boolean(values, "OLLAMA_ENABLED", false)?
            && values.get("OLLAMA_MODEL").is_some_and(|s| !s.is_empty());
        let seconds = values
            .get("LLM_TIMEOUT_SECONDS")
            .map(|s| s.parse::<f64>().unwrap_or(f64::NAN))
            .unwrap_or(30.0);
        if !seconds.is_finite() || !(1.0..=120.0).contains(&seconds) {
            return Err(Failure("invalid_provider_configuration"));
        }
        Ok(Self {
            enabled,
            timeout: Duration::from_secs_f64(seconds),
        })
    }
    pub(crate) fn deadlines(&self) -> (Instant, Instant) {
        let now = Instant::now();
        (
            now + self.timeout.mul_f64(if self.enabled { 0.55 } else { 1.0 }),
            now + self.timeout,
        )
    }
}
pub(crate) fn remaining(deadline: Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or(Failure("timeout"))
}
pub(crate) fn request(
    builder: reqwest::RequestBuilder,
    deadline: Option<Instant>,
) -> Result<reqwest::RequestBuilder> {
    Ok(if let Some(deadline) = deadline {
        builder.timeout(remaining(deadline)?)
    } else {
        builder
    })
}
pub(crate) fn permitted(error: Failure) -> bool {
    matches!(
        error.0,
        "timeout"
            | "rate_limited"
            | "monthly_request_limit"
            | "provider_permission_required"
            | "provider_execution_not_authorized"
            | "candidate_cloud_authorization_required"
            | "cohere_evaluation_authorization_required"
            | "llm_not_configured"
            | "model_unavailable"
            | "provider_authentication"
            | "connection_error"
            | "cohere_transport_error"
            | "provider_error"
            | "invalid_structured_response"
            | "incomplete_generation"
            | "cli_unavailable"
            | "cli_nonzero_exit"
            | "unsupported_cli_argument"
            | "explicit_model_required"
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn local_fallback_needs_independent_local_opt_in_and_never_chains_from_local() {
        let mut values = BTreeMap::new();
        assert!(!Policy::from_values(&values, "cohere").unwrap().enabled);
        values.insert("LLM_LOCAL_FALLBACK_ENABLED".into(), "true".into());
        values.insert("OLLAMA_ENABLED".into(), "true".into());
        values.insert("OLLAMA_MODEL".into(), "fictional:local".into());
        assert!(Policy::from_values(&values, "cohere").unwrap().enabled);
        assert!(!Policy::from_values(&values, "ollama").unwrap().enabled);
        values.insert("OLLAMA_ENABLED".into(), "false".into());
        assert!(!Policy::from_values(&values, "gemini").unwrap().enabled);
    }
    #[test]
    fn primary_slice_and_original_deadline_do_not_refresh_between_attempts() {
        let policy = Policy {
            enabled: true,
            timeout: Duration::from_secs(20),
        };
        let (first, last) = policy.deadlines();
        assert_eq!(last - first, Duration::from_secs(9));
        assert!(remaining(first).unwrap() <= Duration::from_secs(11));
        assert!(remaining(Instant::now() - Duration::from_secs(1)).is_err());
        for raw in ["NaN", "inf", "0", "121"] {
            assert!(
                Policy::from_values(
                    &BTreeMap::from([("LLM_TIMEOUT_SECONDS".into(), raw.into())]),
                    "cohere"
                )
                .is_err()
            );
        }
    }
    #[test]
    fn unknown_ledger_tool_usage_and_context_failures_never_authorize_fallback() {
        for code in [
            "provider_ledger_unavailable",
            "provider_usage_exceeds_reservation",
            "provider_tool_use_denied",
            "generation_context_changed",
            "provider_permission_or_execution_error",
            "provider_init_unverified",
            "owner_workspace_authorization_required",
            "paid_overage_configuration_forbidden",
            "invalid_provider_configuration",
        ] {
            assert!(!permitted(Failure(code)));
        }
        for code in [
            "rate_limited",
            "monthly_request_limit",
            "timeout",
            "connection_error",
            "model_unavailable",
        ] {
            assert!(permitted(Failure(code)));
        }
    }
}
