//! Existing USD numeric ledger. Original reservations never refund or manufacture a transport grant.
use super::money::Usd;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_execution_database_error")
}
fn ack() -> Failure {
    Failure("apify_execution_write_ack_failed")
}
fn invalid() -> Failure {
    Failure("invalid_apify_usd_ledger")
}
pub(super) fn key(id: Uuid) -> String {
    format!("apify_job_{}", id.simple())
}
pub(super) struct Reservation {
    pub(super) row: Value,
    pub(super) monthly: Value,
    pub(super) id: Uuid,
    monthly_exact: String,
    at: DateTime<Utc>,
}
async fn row(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=65536 THEN to_jsonb(r) ELSE NULL END FROM discovery_budget_reservations r WHERE id=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(invalid()),
        None => Ok(None),
    }
}
async fn monthly(tx: &mut Transaction<'_, Postgres>, month: &str) -> Result<Option<Value>> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(b)::text)<=65536 THEN to_jsonb(b) ELSE NULL END FROM discovery_monthly_budgets b WHERE provider='apify' AND month=$1").bind(month).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(invalid()),
        None => Ok(None),
    }
}
pub(super) async fn reserve_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    amount: Usd,
    maximum: Usd,
    at: DateTime<Utc>,
) -> Result<Reservation> {
    if amount.micros() == 0 || amount.micros() > 100_000_000 || amount > maximum || id.is_nil() {
        return Err(invalid());
    }
    if row(tx, id).await?.is_some() {
        return Err(Failure("apify_original_reservation_already_used"));
    }
    let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(at).fetch_one(&mut **tx).await.map_err(db)?;
    if cooling {
        return Err(Failure("apify_execution_cooling_down"));
    }
    let month = at.format("%Y-%m").to_string();
    let previous = monthly(tx, &month).await?;
    let before_amount = if previous.is_some() {
        sqlx::query_scalar::<_,String>("SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify' AND month=$1 FOR UPDATE").bind(&month).fetch_one(&mut **tx).await.map_err(db)?
    } else {
        "0".into()
    };
    let total = Usd::parse(&before_amount)?
        .micros()
        .checked_add(amount.micros())
        .ok_or_else(invalid)?;
    if total > maximum.micros() {
        return Err(Failure("apify_execution_budget_exhausted"));
    }
    let total = format!("{}.{:06}", total / 1_000_000, total % 1_000_000);
    let values = json!({"id":key(id),"provider":"apify","month":month,"reserved":amount.decimal(),"provider_run_id":null,"reported_actual":null,"state":"reserved","created_at":at.to_rfc3339()});
    let expected: Value = sqlx::query_scalar(
        "SELECT to_jsonb(jsonb_populate_record(NULL::discovery_budget_reservations,$1))",
    )
    .bind(values)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_budget_reservations AS r(id,provider,month,reserved,provider_run_id,reported_actual,state,created_at) SELECT x.id,x.provider,x.month,x.reserved,x.provider_run_id,x.reported_actual,x.state,x.created_at FROM jsonb_populate_record(NULL::discovery_budget_reservations,$1) x RETURNING to_jsonb(r)").bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let monthly = if let Some(before) = previous {
        let mut next = before.clone();
        let numeric: Value = sqlx::query_scalar("SELECT to_jsonb($1::numeric(16,6))")
            .bind(&total)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
        next["reserved"] = numeric;
        let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_monthly_budgets AS b SET reserved=$2::numeric WHERE provider='apify' AND month=$1 AND to_jsonb(b)=$3 AND reserved=$4::numeric RETURNING to_jsonb(b)").bind(&month).bind(&total).bind(&before).bind(&before_amount).fetch_optional(&mut **tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next) {
            return Err(ack());
        }
        next
    } else {
        let next:Value=sqlx::query_scalar("SELECT to_jsonb(jsonb_populate_record(NULL::discovery_monthly_budgets,jsonb_build_object('provider','apify','month',$1::text,'reserved',$2::numeric,'cooldown_until',NULL)))").bind(&month).bind(&total).fetch_one(&mut **tx).await.map_err(db)?;
        let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_monthly_budgets AS b(provider,month,reserved,cooldown_until) VALUES('apify',$1,$2::numeric,NULL) RETURNING to_jsonb(b)").bind(&month).bind(&total).fetch_optional(&mut **tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next) {
            return Err(ack());
        }
        next
    };
    let reservation = Reservation {
        row: expected,
        monthly,
        id,
        monthly_exact: total,
        at,
    };
    reservation.verify_in(tx).await?;
    Ok(reservation)
}
impl Reservation {
    pub(super) async fn verify_in(&self, tx: &mut Transaction<'_, Postgres>) -> Result<()> {
        let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(self.at).fetch_one(&mut **tx).await.map_err(db)?;
        if cooling {
            return Err(ack());
        }
        let exact:Option<bool>=sqlx::query_scalar("SELECT reserved=$2::numeric FROM discovery_monthly_budgets WHERE provider='apify' AND month=$1").bind(self.row["month"].as_str()).bind(&self.monthly_exact).fetch_optional(&mut **tx).await.map_err(db)?;
        if exact != Some(true) {
            return Err(ack());
        }
        if row(tx, self.id).await?.as_ref() != Some(&self.row)
            || monthly(tx, self.row["month"].as_str().ok_or_else(invalid)?)
                .await?
                .as_ref()
                != Some(&self.monthly)
        {
            return Err(ack());
        }
        Ok(())
    }
}
pub(super) async fn read_reserved_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    expected: &Value,
) -> Result<Value> {
    let row = row(tx, id)
        .await?
        .ok_or(Failure("apify_original_reservation_missing"))?;
    if row != *expected
        || row["provider"] != "apify"
        || row["id"] != key(id)
        || !matches!(row["state"].as_str(), Some("reserved" | "run_attached"))
        || row["state"] == "reserved" && !row["provider_run_id"].is_null()
        || row["state"] == "run_attached"
            && row["provider_run_id"].as_str().is_none_or(|s| {
                s.is_empty()
                    || s.len() > 100
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            })
        || !row["reported_actual"].is_null()
    {
        return Err(Failure("apify_original_reservation_changed"));
    }
    let amount: String =
        sqlx::query_scalar("SELECT reserved::text FROM discovery_budget_reservations WHERE id=$1")
            .bind(key(id))
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    let amount = Usd::parse(&amount)?;
    if amount.micros() == 0 || amount.micros() > 100_000_000 {
        return Err(invalid());
    }
    let covered:Option<bool>=sqlx::query_scalar("SELECT reserved>=$2::numeric FROM discovery_monthly_budgets WHERE provider='apify' AND month=$1").bind(row["month"].as_str()).bind(amount.decimal()).fetch_optional(&mut **tx).await.map_err(db)?;
    if covered != Some(true) {
        return Err(Failure("apify_original_reservation_changed"));
    }
    Ok(
        json!({"reservation_id":key(id),"month":row["month"],"reserved_usd":amount.decimal(),"accounting":"full_cap_retained","billing_final":false,"record_basis":"original_local_numeric_reservation"}),
    )
}
pub(super) async fn attach_in(
    tx: &mut Transaction<'_, Postgres>,
    request: Uuid,
    expected: &Value,
    run: &Value,
) -> Result<Value> {
    read_reserved_in(tx, request, expected).await?;
    let run_id = run["id"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 100
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        })
        .ok_or_else(invalid)?;
    if !expected["provider_run_id"].is_null() && expected["provider_run_id"] != run_id {
        return Err(Failure("apify_run_original_binding_changed"));
    }
    let other:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_budget_reservations WHERE provider='apify' AND provider_run_id=$1 AND id<>$2)").bind(run_id).bind(key(request)).fetch_one(&mut **tx).await.map_err(db)?;
    if other {
        return Err(Failure("apify_run_original_binding_changed"));
    }
    let mut next = expected.clone();
    next["provider_run_id"] = json!(run_id);
    next["state"] = json!("run_attached");
    if next != *expected {
        let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_budget_reservations AS r SET provider_run_id=$2,state='run_attached' WHERE id=$1 AND to_jsonb(r)=$3 RETURNING to_jsonb(r)").bind(key(request)).bind(run_id).bind(expected).fetch_optional(&mut **tx).await.map_err(db)?;
        if saved.as_ref() != Some(&next) {
            return Err(ack());
        }
    }
    read_reserved_in(tx, request, &next).await?;
    Ok(next)
}
pub(super) async fn monthly_snapshot_in(
    tx: &mut Transaction<'_, Postgres>,
    reservation: &Value,
) -> Result<(Value, String)> {
    let month = reservation["month"].as_str().ok_or_else(invalid)?;
    let row = monthly(tx, month).await?.ok_or_else(invalid)?;
    let numeric: String = sqlx::query_scalar(
        "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify' AND month=$1",
    )
    .bind(month)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    Ok((row, numeric))
}
