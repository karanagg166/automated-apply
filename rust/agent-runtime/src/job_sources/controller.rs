//! Original acquisition retains selected observations; no queue/job/company writes occur here.
use super::{
    access::{self, Admission},
    plan::Source,
    transport::Client,
};
use crate::{Failure, Result, source_registry::Settings};
use serde_json::Value;
use sqlx::PgConnection;
use uuid::Uuid;
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
}
impl Service<'_> {
    pub async fn acquire(
        &self,
        c: &mut PgConnection,
        source: Source,
        query: Value,
        id: Uuid,
    ) -> Result<Value> {
        match access::admit(c, self.settings, source, query, id).await? {
            Admission::Retained(v) => Ok(v),
            Admission::Original(claim) => acquire_original(c, self.client, *claim).await,
        }
    }
    pub async fn read(&self, c: &mut PgConnection, id: Uuid) -> Result<Value> {
        access::read(c, id).await
    }
}
pub(super) async fn acquire_original(
    c: &mut PgConnection,
    client: &Client,
    mut claim: access::Claim,
) -> Result<Value> {
    let grant = claim
        .grant
        .take()
        .ok_or(Failure("public_job_original_grant_missing"))?;
    let outcome = client.execute(grant).await;
    super::findings::retain(c, claim, outcome).await
}
