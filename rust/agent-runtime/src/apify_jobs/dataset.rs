//! Shared bounded dataset selection. Only normalized claims survive; inconsistent duplicate IDs are removed.
use super::plan::Plan;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub(super) fn page(
    plan: &Plan,
    run_id: &str,
    body: &Value,
    offset: u64,
    observed: DateTime<Utc>,
) -> Result<Value> {
    let limit = plan.query["limit"]
        .as_u64()
        .ok_or(Failure("invalid_apify_original_intent"))?;
    if offset >= limit || !offset.is_multiple_of(50) {
        return Err(Failure("apify_dataset_target_denied"));
    }
    let max = 50.min(limit - offset);
    let rows = body
        .as_array()
        .filter(|a| a.len() as u64 <= max)
        .ok_or(Failure("apify_dataset_schema_invalid"))?;
    let mut selected = Vec::new();
    let mut rejected = 0;
    for row in rows {
        match super::record::normalize(
            plan.portal(),
            plan.actor["actor_id"]
                .as_str()
                .ok_or(Failure("apify_actor_id_invalid"))?,
            row,
            observed,
        ) {
            Ok(mut job) => {
                job["data_provenance"]["provider_run_id"] = json!(run_id);
                job["data_provenance"]["actor_build"] = plan.actor["build"].clone();
                selected.push(job);
            }
            Err(_) => rejected += 1,
        }
    }
    Ok(
        json!({"offset":offset,"limit":max,"returned":rows.len(),"rejected":rejected,"jobs":selected,"observed_at":observed.to_rfc3339()}),
    )
}
#[derive(Default)]
pub(super) struct Selection {
    jobs: BTreeMap<String, Value>,
    conflicts: BTreeSet<String>,
    rejected: u64,
    duplicate: u64,
    returned: u64,
}
impl Selection {
    pub(super) fn push(&mut self, page: &Value) -> Result<()> {
        let returned = page["returned"]
            .as_u64()
            .filter(|n| *n <= 50)
            .ok_or(Failure("apify_dataset_schema_invalid"))?;
        let rejected = page["rejected"]
            .as_u64()
            .filter(|n| *n <= returned)
            .ok_or(Failure("apify_dataset_schema_invalid"))?;
        let rows = page["jobs"]
            .as_array()
            .filter(|a| a.len() as u64 + rejected == returned)
            .ok_or(Failure("apify_dataset_schema_invalid"))?;
        if self.returned + returned > 100 {
            return Err(Failure("apify_dataset_schema_invalid"));
        }
        self.returned += returned;
        self.rejected += rejected;
        for job in rows {
            let identity = crate::job_sources::identity::observation_key(job)?;
            if self.conflicts.contains(&identity) {
                self.rejected += 1;
                continue;
            }
            if let Some(previous) = self.jobs.get(&identity) {
                if previous == job {
                    self.duplicate += 1
                } else {
                    self.jobs.remove(&identity);
                    self.conflicts.insert(identity);
                    self.rejected += 2;
                }
            } else {
                self.jobs.insert(identity, job.clone());
            }
        }
        Ok(())
    }
    pub(super) fn finding(self, source: &str, at: DateTime<Utc>) -> Value {
        let jobs = self.jobs.into_values().collect::<Vec<_>>();
        json!({"source":source,"status":if self.rejected>0{"partial"}else if jobs.is_empty(){"no_results"}else{"success"},"jobs":jobs,"rejected_count":self.rejected,"duplicate_count":self.duplicate,"observed_at":at.to_rfc3339(),"application_dispatch":false,"live_verified":false,"billing_final":false})
    }
}
