//! Owner-only consistent read snapshots. No URL/resume fetch and no admission side effects.
use crate::{Failure, Result, profile_store, resources};
use serde_json::Value;
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}

pub async fn inspect(
    connection: &mut PgConnection,
    selected: Option<Uuid>,
    readiness: bool,
    live: bool,
) -> Result<Value> {
    let mut transaction = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    let profile = match profile_store::get(&mut transaction).await {
        Ok(saved) => Some(saved.value),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    let mut saved = Vec::new();
    if let Some(profile) = &profile {
        let id = profile["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_profile_record"))?;
        // Never silently choose a primary from a truncated resource inventory.
        let rows: Vec<Value> = sqlx::query_scalar("SELECT to_jsonb(r) FROM (SELECT id,resource_type,label,url,user_confirmed,is_primary,source_type,updated_at FROM candidate_resources WHERE candidate_profile_id=$1 ORDER BY created_at,id LIMIT 10001) r")
            .bind(id).fetch_all(&mut *transaction).await.map_err(db)?;
        if rows.len() > 10000 {
            return Err(Failure("resource_inventory_limit"));
        }
        for row in rows {
            saved.push(
                serde_json::from_value::<resources::Resource>(row)
                    .map_err(|_| Failure("invalid_resource_record"))?,
            );
        }
    }
    let output = if readiness {
        resources::assess_profile(profile, &saved, live)?
    } else {
        if profile.is_none() {
            return Err(Failure("profile_not_found"));
        }
        serde_json::to_value(resources::select_resume(&saved, selected)?)
            .map_err(|_| Failure("invalid_resource_record"))?
    };
    transaction.commit().await.map_err(db)?;
    Ok(output)
}
