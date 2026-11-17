//! Source observation identity stays fixed; older observations cannot replace newer provenance.
use super::sql::{self, Table, db, id, invalid};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn save(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    job: Uuid,
    before: Option<Value>,
    reason: &str,
) -> Result<Value> {
    let identity = super::super::identity::observation_key(item)?;
    let provenance = sql::provenance(item, reason);
    if let Some(before) = before {
        if before["job_id"] != json!(job)
            || before["source"] != item["source_name"]
            || before["identity_key"] != identity
            || before["source_job_id"] != item["source_job_id"]
        {
            return Err(Failure("public_job_source_identity_conflict"));
        }
        let old = super::super::access::time(&before["last_observed_at"])?;
        let incoming = super::super::access::time(&item["last_observed_date"])?;
        if incoming < old {
            return Ok(before);
        }
        if incoming == old
            && (before["original_url"] != item["original_url"]
                || before["verification_status"] != item["source_verification_status"]
                || before["provenance"] != provenance)
        {
            // Deduplication reason may legitimately change from new_job to source_identity.
            let mut previous = before["provenance"].clone();
            let mut current = provenance.clone();
            if !previous.is_object() || !current.is_object() {
                return Err(invalid());
            }
            previous
                .as_object_mut()
                .ok_or_else(invalid)?
                .remove("deduplication");
            current
                .as_object_mut()
                .ok_or_else(invalid)?
                .remove("deduplication");
            if previous != current
                || before["original_url"] != item["original_url"]
                || before["verification_status"] != item["source_verification_status"]
            {
                return Err(Failure("public_job_same_time_observation_conflict"));
            }
            return Ok(before);
        }
        let expected=sql::patch(tx,Table::Observation,&before,json!({"last_observed_at":item["last_observed_date"],"provenance":provenance,"original_url":item["original_url"],"verification_status":item["source_verification_status"]})).await?;
        if expected == before {
            return Ok(before);
        }
        let saved:Option<Value>=sqlx::query_scalar("UPDATE job_source_observations AS o SET last_observed_at=x.last_observed_at,provenance=x.provenance,original_url=x.original_url,verification_status=x.verification_status FROM jsonb_populate_record(NULL::job_source_observations,$2) x WHERE o.id=$1 RETURNING to_jsonb(o)").bind(id(&before["id"])?).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
        return sql::acknowledged(tx, Table::Observation, expected, saved, false).await;
    }
    let values = json!({"id":Uuid::new_v4(),"job_id":job,"source":item["source_name"],"identity_key":identity,"source_job_id":item["source_job_id"],"original_url":item["original_url"],"first_observed_at":item["first_observed_date"],"last_observed_at":item["last_observed_date"],"provenance":provenance,"verification_status":item["source_verification_status"]});
    let expected = sql::typed(tx, Table::Observation, &values).await?;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO job_source_observations AS o(id,job_id,source,identity_key,source_job_id,original_url,first_observed_at,last_observed_at,provenance,verification_status) SELECT x.id,x.job_id,x.source,x.identity_key,x.source_job_id,x.original_url,x.first_observed_at,x.last_observed_at,x.provenance,x.verification_status FROM jsonb_populate_record(NULL::job_source_observations,$1) x RETURNING to_jsonb(o)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    sql::acknowledged(tx, Table::Observation, expected, saved, false).await
}
