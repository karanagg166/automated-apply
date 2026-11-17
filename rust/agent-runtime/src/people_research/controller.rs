//! Original owner research orchestration. Transports run after admission and outside transactions.
use super::{
    runs::{self, Admission},
    settings::Settings,
    transport::Client,
};
use crate::{Failure, Result};
use serde_json::Value;
use sqlx::PgConnection;
use uuid::Uuid;
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: Option<&'a Client>,
    pub contacts: &'a crate::contacts::Settings,
}
impl Service<'_> {
    pub async fn run(&self, c: &mut PgConnection, input: Value, request: Uuid) -> Result<Value> {
        let finding = self.acquire(c, input, request).await?;
        if finding["recorded_state"] == "finding_retained"
            && matches!(
                finding["provider_status"].as_str(),
                Some("success" | "partial" | "no_results")
            )
        {
            return super::completion::apply(c, request, self.settings, self.contacts).await;
        }
        Ok(finding)
    }
    /// Retain the original transport result before local completion. Never fetches result pages.
    pub async fn acquire(
        &self,
        c: &mut PgConnection,
        input: Value,
        request: Uuid,
    ) -> Result<Value> {
        // Preserve omission/default serialization by forwarding the original input to admission.
        let normalized = crate::research_contract::normalize(
            crate::research_contract::Kind::PeopleQuery,
            input.clone(),
            chrono::Utc::now(),
        )?;
        if normalized["source"] == "manual" {
            return super::ingest::manual(c, input, request, self.contacts).await;
        }
        if normalized["source"] != "public_search" {
            return Err(Failure("public_research_direct_collection_unavailable"));
        }
        match runs::admit(c, input, request, self.settings).await? {
            Admission::Retained(value) => Ok(value),
            Admission::Original(mut claim) => {
                let client = self
                    .client
                    .ok_or(Failure("public_research_local_client_unavailable"))?;
                let grant = claim
                    .grant
                    .take()
                    .ok_or(Failure("public_research_original_grant_unavailable"))?;
                let outcome = client.execute(grant).await;
                super::findings::retain(c, &claim, &outcome).await
            }
        }
    }
    pub async fn read(&self, c: &mut PgConnection, request: Uuid) -> Result<Value> {
        match runs::retained(c, request).await {
            Err(e) if e.0 == "public_research_request_not_found" => {
                super::ingest::retained(c, request).await
            }
            value => value,
        }
    }
}
