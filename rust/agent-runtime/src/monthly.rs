//! Shares the legacy monthly ledger: Rust never resets or duplicates approved budgets.
use crate::{Failure, Result};
use sqlx::{Connection, PgConnection, Row};

#[derive(Clone, Copy)]
pub struct MonthlyPolicy {
    pub requests: u32,
    pub cohere_requests: u32,
    pub cohere_tokens: u32,
    pub reserved_input_bytes: u32,
    pub reserved_output_tokens: u32,
}
impl MonthlyPolicy {
    pub fn maximum(self) -> Result<i32> {
        let per = self
            .reserved_input_bytes
            .saturating_add(self.reserved_output_tokens);
        if per == 0
            || self.requests > 10000
            || self.cohere_requests > 1000
            || self.cohere_tokens > 10000000
        {
            return Err(Failure("invalid_provider_budget"));
        }
        let cap = self
            .requests
            .min(self.cohere_requests)
            .min(self.cohere_tokens / per);
        if cap == 0 {
            return Err(Failure("monthly_request_limit"));
        }
        Ok(cap as i32)
    }
}
// Kept opaque: only a successfully committed reservation produces a Month.
pub struct Month(String);
pub async fn reserve(connection: &mut PgConnection, policy: MonthlyPolicy) -> Result<Month> {
    let maximum = policy.maximum()?;
    let mut transaction = connection
        .begin()
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    sqlx::query("SELECT pg_advisory_xact_lock(166001,51)")
        .execute(&mut *transaction)
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    let paused:bool=sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM llm_monthly_usage WHERE provider='cohere' AND cooldown_until>clock_timestamp())").fetch_one(&mut *transaction).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    if paused {
        return Err(Failure("rate_limited"));
    }
    let row=sqlx::query("INSERT INTO llm_monthly_usage (provider,month,requests,input_tokens,output_tokens,cooldown_until,created_at,updated_at) VALUES ('cohere',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),1,0,0,clock_timestamp()+interval '3.1 seconds',clock_timestamp(),clock_timestamp()) ON CONFLICT (provider,month) DO UPDATE SET requests=llm_monthly_usage.requests+1,updated_at=clock_timestamp(),cooldown_until=clock_timestamp()+interval '3.1 seconds' WHERE llm_monthly_usage.requests<$1 AND (llm_monthly_usage.cooldown_until IS NULL OR llm_monthly_usage.cooldown_until<=clock_timestamp()) RETURNING month")
        .bind(maximum).fetch_optional(&mut *transaction).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    let month = row
        .map(|row| {
            row.try_get("month")
                .map_err(|_| Failure("provider_ledger_unavailable"))
        })
        .transpose()?
        .ok_or(Failure("monthly_request_limit"))?;
    transaction
        .commit()
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    Ok(Month(month))
}

pub async fn tokens(
    connection: &mut PgConnection,
    month: &Month,
    input: Option<u32>,
    output: Option<u32>,
) -> Result<()> {
    sqlx::query("UPDATE llm_monthly_usage SET input_tokens=input_tokens+$1,output_tokens=output_tokens+$2,updated_at=clock_timestamp() WHERE provider='cohere' AND month=$3")
        .bind(i64::from(input.unwrap_or(0))).bind(i64::from(output.unwrap_or(0))).bind(&month.0).execute(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(())
}
pub async fn cooldown(connection: &mut PgConnection, month: &Month, seconds: u32) -> Result<()> {
    sqlx::query("UPDATE llm_monthly_usage SET cooldown_until=GREATEST(COALESCE(cooldown_until,clock_timestamp()),clock_timestamp()+$1*interval '1 second'),updated_at=clock_timestamp() WHERE provider='cohere' AND month=$2")
        .bind(f64::from(seconds.clamp(60,31536000))).bind(&month.0).execute(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(())
}
