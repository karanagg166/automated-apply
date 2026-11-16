//! Bounded local-first owner orchestration. All remote calls happen outside transactions.
use super::*;
use std::time::{Duration, Instant};
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub contacts: &'a super::super::Settings,
    pub clients: &'a providers::Clients,
    pub eligibility: &'a capabilities::Eligibility,
}
struct Finding {
    state: &'static str,
    contacts: Vec<Uuid>,
    fallback: bool,
    error: Option<&'static str>,
}
fn infrastructure(error: Failure) -> bool {
    error.0.contains("database_error")
        || error.0.contains("write_ack_failed")
        || error.0.contains("commit")
        || error.0.starts_with("invalid_contact_saved")
}
impl Service<'_> {
    async fn call(
        &self,
        c: &mut PgConnection,
        run: &runs::Run,
        provider: &str,
        target: lookups::Target,
        deadline: Instant,
    ) -> Result<Finding> {
        let client = match self.clients.get(provider) {
            Ok(client) => client,
            Err(error) => {
                return Ok(Finding {
                    state: "not_configured",
                    contacts: Vec::new(),
                    fallback: false,
                    error: Some(error.0),
                });
            }
        };
        if deadline.saturating_duration_since(Instant::now())
            < client.timeout() + Duration::from_secs(17)
        {
            return Ok(Finding {
                state: "failed",
                contacts: Vec::new(),
                fallback: false,
                error: Some("contact_run_time_budget_exhausted"),
            });
        }
        let claim =
            match lookups::prepare(c, run, provider, target, self.settings, self.contacts).await {
                Ok(claim) => claim,
                Err(error) if !infrastructure(error) => {
                    return Ok(Finding {
                        state: match error.0 {
                            "contact_lookup_not_needed" => "completed",
                            "contact_provider_not_configured"
                            | "contact_lookup_cost_review_required" => "not_configured",
                            "contact_provider_budget_exhausted"
                            | "contact_provider_run_budget_exhausted" => "budget_exhausted",
                            _ => "failed",
                        },
                        contacts: Vec::new(),
                        fallback: false,
                        error: Some(error.0),
                    });
                }
                Err(error) => return Err(error),
            };
        let operation = if matches!(target, lookups::Target::Search) {
            capabilities::Operation::Search
        } else {
            capabilities::Operation::Enrich
        };
        let cost = claim
            .reservation()
            .map(budget::Reservation::amount)
            .unwrap_or(0);
        let proof = match tokio::time::timeout(
            Duration::from_secs(15),
            client.introspect(operation, cost, self.eligibility),
        )
        .await
        {
            Ok(Ok(proof)) => proof,
            Ok(Err(error)) => {
                return Ok(Finding {
                    state: error.state,
                    contacts: Vec::new(),
                    fallback: false,
                    error: Some(error.code),
                });
            }
            Err(_) => {
                return Ok(Finding {
                    state: "failed",
                    contacts: Vec::new(),
                    fallback: false,
                    error: Some("contact_provider_metadata_deadline"),
                });
            }
        };
        let grant =
            match dispatch::authorize(c, run, &claim, proof, client, self.settings, self.contacts)
                .await
            {
                Ok(grant) => grant,
                Err(error) if !infrastructure(error) => {
                    return Ok(Finding {
                        state: "failed",
                        contacts: Vec::new(),
                        fallback: false,
                        error: Some(error.0),
                    });
                }
                Err(error) => return Err(error),
            };
        let outcome = client.execute(grant).await;
        results::record(c, run, &claim, &outcome).await?;
        let ingested = results::ingest(c, run, &claim, self.settings, self.contacts).await?;
        let mut contacts = Vec::new();
        for finding in ingested["findings"].as_array().ok_or_else(invalid)? {
            if let Some(id) = finding["contact_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
            {
                if !contacts.contains(&id) {
                    contacts.push(id);
                }
            }
        }
        let error = if ingested["held_reason"].is_null() {
            if ingested["findings"]
                .as_array()
                .is_some_and(|f| f.iter().any(|f| f["requires_review"] == true))
            {
                Some("contact_provider_identity_requires_review")
            } else {
                outcome.error_code
            }
        } else {
            Some("contact_provider_result_held_for_review")
        };
        Ok(Finding {
            state: outcome.state,
            contacts,
            fallback: ingested["usable_profile_result"] == true
                && ingested["missing_business_email"] == true,
            error,
        })
    }
    pub async fn enrich(&self, c: &mut PgConnection, company: Uuid, input: Value) -> Result<Value> {
        let started = runs::start(c, company, input, self.settings).await?;
        let Some(run) = started.invocation else {
            return Ok(started.record);
        };
        let deadline = Instant::now() + Duration::from_secs(80);
        let local = match local::collect(c, &run, self.settings, self.contacts).await {
            Ok(local) => local,
            Err(error) if !infrastructure(error) => {
                return runs::finish(c, &run, &[], &[error.0], "failed").await;
            }
            Err(error) => return Err(error),
        };
        let mut selected = local.selected;
        let mut errors = local.errors;
        let mut state = "completed";
        let maximum = run.input()["max_people"]
            .as_i64()
            .ok_or_else(invalid)?
            .min(self.settings.max_people) as usize;
        let requested = run.input()["providers"].as_array().ok_or_else(invalid)?;
        if run.input()["allow_paid"] == true && !requested.is_empty() {
            if selected.is_empty() && requested.first() == Some(&json!("apollo")) {
                let finding = self
                    .call(c, &run, "apollo", lookups::Target::Search, deadline)
                    .await?;
                state = finding.state;
                if let Some(error) = finding.error {
                    errors.push(error);
                }
                selected.extend(finding.contacts.into_iter().take(maximum));
            }
            let mut blocked = BTreeSet::new();
            for contact in selected.clone().into_iter().take(maximum) {
                if !local::lookup_needed(c, &run, contact, self.settings, self.contacts).await? {
                    continue;
                }
                let mut previous_fallback = false;
                for (index, name) in requested.iter().enumerate() {
                    let name = name.as_str().ok_or_else(invalid)?;
                    if blocked.contains(name)
                        || index > 0
                            && (run.input()["allow_fallback"] != true || !previous_fallback)
                    {
                        break;
                    }
                    let finding = self
                        .call(c, &run, name, lookups::Target::Contact(contact), deadline)
                        .await?;
                    previous_fallback = finding.fallback;
                    if let Some(error) = finding.error {
                        if error != "contact_lookup_not_needed" {
                            errors.push(error);
                        }
                    }
                    if matches!(
                        finding.state,
                        "authorization_required"
                            | "rate_limited"
                            | "billing_uncertain"
                            | "failed"
                            | "queued"
                            | "running"
                    ) {
                        blocked.insert(name.to_owned());
                    }
                    if finding.state != "completed" {
                        state = finding.state;
                    }
                }
            }
        }
        selected.sort();
        selected.dedup();
        selected.truncate(maximum);
        errors.sort();
        errors.dedup();
        let references = errors.iter().copied().take(100).collect::<Vec<_>>();
        runs::finish(c, &run, &selected, &references, state).await
    }
}
