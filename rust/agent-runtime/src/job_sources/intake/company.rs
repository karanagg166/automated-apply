//! Employer source identity precedes display-name lookup; known company facts remain intact.
use super::sql::{self, Table, db, invalid};
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn resolve(
    tx: &mut Transaction<'_, Postgres>,
    item: &Value,
    prior: Option<Uuid>,
) -> Result<Value> {
    let domain = item["company_domain"].as_str();
    let name = item["company_name"].as_str().ok_or_else(invalid)?;
    let domain_ids: Vec<Uuid> = if let Some(domain) = domain {
        sqlx::query_scalar("SELECT id FROM companies WHERE domain=$1 ORDER BY id LIMIT 2")
            .bind(domain)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?
    } else {
        vec![]
    };
    if domain_ids.len() > 1 {
        return Err(Failure("public_job_company_identity_ambiguous"));
    }
    if let Some(prior) = prior {
        let saved = sql::row(tx, Table::Company, prior).await?;
        if super::super::identity::folded(saved["name"].as_str())
            != super::super::identity::folded(Some(name))
            || domain_ids.first().is_some_and(|v| *v != prior)
            || domain.is_some()
                && !saved["domain"].is_null()
                && saved["domain"] != item["company_domain"]
        {
            return Err(Failure("public_job_company_identity_conflict"));
        }
        // Existing job-to-company identity wins; name-only evidence cannot promote its domain.
        return Ok(saved);
    }
    if let Some(id) = domain_ids.first() {
        return sql::row(tx, Table::Company, *id).await;
    }
    let names: Vec<Uuid> =
        sqlx::query_scalar("SELECT id FROM companies WHERE lower(name)=$1 ORDER BY id LIMIT 2")
            .bind(name.trim().to_lowercase())
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let ambiguous = names.len() > 1;
    let candidate = if names.len() == 1 {
        names.first().copied()
    } else if ambiguous && domain.is_none() {
        let ids: Vec<Uuid> = sqlx::query_scalar(
            "SELECT id FROM companies WHERE lower(name)=$1 AND domain IS NULL ORDER BY id LIMIT 2",
        )
        .bind(name.trim().to_lowercase())
        .fetch_all(&mut **tx)
        .await
        .map_err(db)?;
        if ids.len() == 1 {
            ids.first().copied()
        } else {
            None
        }
    } else {
        None
    };
    if let Some(candidate) = candidate {
        let before = sql::row(tx, Table::Company, candidate).await?;
        if !before["metadata"].is_object() && !before["metadata"].is_null() {
            return Err(invalid());
        }
        let review =
            crate::contacts::rules::truthy(&before["metadata"]["identity_review_required"]);
        if domain.is_none()
            || !review && (before["domain"].is_null() || before["domain"] == item["company_domain"])
        {
            if domain.is_some() && before["domain"].is_null() {
                let stamp = sql::stamp(tx).await?;
                let expected = sql::patch(
                    tx,
                    Table::Company,
                    &before,
                    json!({"domain":domain,"updated_at":stamp}),
                )
                .await?;
                let saved:Option<Value>=sqlx::query_scalar("UPDATE companies c SET domain=$2->>'domain',updated_at=($2->>'updated_at')::timestamptz WHERE id=$1 RETURNING to_jsonb(c)").bind(candidate).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
                return sql::acknowledged(tx, Table::Company, expected, saved, true).await;
            }
            return Ok(before);
        }
    }
    let stamp = sql::stamp(tx).await?;
    let values = json!({"id":Uuid::new_v4(),"name":name.trim(),"domain":domain,"linkedin_url":null,"email_pattern":null,"is_catch_all":false,"metadata":if ambiguous && domain.is_none(){json!({"identity_review_required":true,"identity_resolution":"ambiguous_name_without_domain"})}else{json!({})},"created_at":stamp,"updated_at":stamp});
    let expected = sql::typed(tx, Table::Company, &values).await?;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO companies AS c(id,name,domain,linkedin_url,email_pattern,is_catch_all,metadata,created_at,updated_at) SELECT x.id,x.name,x.domain,x.linkedin_url,x.email_pattern,x.is_catch_all,x.metadata,x.created_at,x.updated_at FROM jsonb_populate_record(NULL::companies,$1) x RETURNING to_jsonb(c)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    sql::acknowledged(tx, Table::Company, expected, saved, true).await
}
