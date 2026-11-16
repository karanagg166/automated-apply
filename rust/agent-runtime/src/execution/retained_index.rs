//! Index existing genuine owner UI observations as history; never create an application attempt.
use super::{events, receipts, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
async fn pending(c: &mut PgConnection) -> Result<Vec<(String, Value, DateTime<Utc>)>> {
    let cursor: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='apply_history_cursor'")
            .fetch_optional(&mut *c)
            .await
            .map_err(db)?;
    let after = cursor
        .as_ref()
        .map(|v| timestamp(&v["updated_at"]))
        .transpose()?;
    let key = cursor
        .as_ref()
        .map(|v| v["key"].as_str().ok_or_else(invalid))
        .transpose()?;
    sqlx::query_as("SELECT key,value,updated_at FROM owner_preferences WHERE starts_with(key,'naukri_receipt:') AND ($1::timestamptz IS NULL OR (updated_at,key)>($1,$2)) ORDER BY updated_at,key LIMIT 5").bind(after).bind(key).fetch_all(c).await.map_err(db)
}
fn protected(value: &Value) -> Result<bool> {
    let stage = value["stage"].as_str().ok_or_else(invalid)?;
    let actions = value["admitted_actions"].as_array().ok_or_else(invalid)?;
    Ok(matches!(
        stage,
        "SUBMITTED_RECORDED" | "SUBMITTED_CONFIRMED" | "SUBMISSION_UNKNOWN"
    ) || !actions.is_empty()
        || !value["packet_id"].is_null()
        || value["form_pending"] == true
        || matches!(
            value["status"].as_str(),
            Some("leased" | "executing" | "unknown")
        )
        || !value["lease_token"].is_null()
        || !value["lease_until"].is_null())
}
pub async fn tick(c: &mut PgConnection) -> Result<usize> {
    if pending(c).await?.is_empty() {
        return Ok(0);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result=async{
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE").execute(&mut *tx).await.map_err(db)?;lock(&mut tx).await?;
        let records=pending(&mut tx).await?;let now=now(&mut tx).await?;let mut added=0;
        for(key,source,_)in &records{
            if !receipts::recorded_application(key,source,now){continue;}
            let req=source["requisition"].as_str().ok_or_else(invalid)?;
            let identity=Uuid::new_v5(&Uuid::NAMESPACE_URL,format!("naukri:{req}").as_bytes());let key=format!("apply_work:{identity}");
            let mut value=if let Some(value)=get(&mut tx,&key).await?{
                if value["id"]!=identity.to_string()||value["platform"]!="naukri"||value["requisition"]!=req{return Err(invalid());}
                if protected(&value)?{continue;}value
            }else{json!({"id":identity,"platform":"naukri","requisition":req,"url":null,"job_id":null,"packet_id":null,"source":"retained_receipt","facts":{},"location":null,"match_score":null,"attempts":0,"revision":0,"created_at":source["observed_at"],"admitted_actions":[]})};
            value["stage"]=json!("SUBMITTED_RECORDED");value["status"]=json!("complete");value["operation"]=Value::Null;value["title"]=source["job_title"].clone();value["company"]=source["hiring_company"].clone();value["reason"]=json!("retained_provider_ui_observation");value["revision"]=json!(next(&value)?);value["updated_at"]=json!(stamp(now));value["lease_until"]=Value::Null;value["lease_token"]=Value::Null;value["binding"]=Value::Null;value["submission_mode"]=source["operation_mode"].clone();value["receipt_source"]=source["confirmation_source"].clone();
            put(&mut tx,&key,&value).await?;events::queue(&mut tx,&value,"retained_receipt_indexed",now).await?;added+=1;
        }
        if let Some((key,_,updated))=records.last(){put(&mut tx,"apply_history_cursor",&json!({"updated_at":stamp(*updated),"key":key})).await?;}
        Ok(added)
    }.await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
