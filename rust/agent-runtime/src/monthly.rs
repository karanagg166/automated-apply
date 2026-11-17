//! Shares the legacy monthly ledger: Rust never resets or duplicates approved budgets.
use crate::{Failure, Result};
use sqlx::{Connection, PgConnection, Postgres, Transaction};

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
pub struct Month(String, Provider);
#[derive(Clone, Copy)]
enum Provider {
    Cohere,
    Gemini,
    Agy,
}
impl Provider {
    fn name(self) -> &'static str {
        match self {
            Self::Cohere => "cohere",
            Self::Gemini => "gemini",
            Self::Agy => "agy",
        }
    }
}
pub async fn reserve(connection: &mut PgConnection, policy: MonthlyPolicy) -> Result<Month> {
    reserve_capped(connection, Provider::Cohere, policy.maximum()?, 3.1).await
}
/// Preserve both the shared configured request cap and the separate owner Gemini grant.
pub async fn reserve_gemini(
    connection: &mut PgConnection,
    configured: u32,
    approved: u32,
) -> Result<Month> {
    if configured > 10000 || approved > 10000 {
        return Err(Failure("invalid_provider_budget"));
    }
    let maximum = configured.min(approved);
    if maximum == 0 {
        return Err(Failure("monthly_request_limit"));
    }
    reserve_capped(connection, Provider::Gemini, maximum as i32, 0.0).await
}
pub(crate) async fn reserve_cli(connection: &mut PgConnection, configured: u32) -> Result<Month> {
    if configured == 0 {
        return Err(Failure("monthly_request_limit"));
    }
    if configured > 10000 {
        return Err(Failure("invalid_provider_budget"));
    }
    reserve_capped(connection, Provider::Agy, configured as i32, 0.0).await
}
pub(crate) async fn gemini_retry_after(connection: &mut PgConnection) -> Result<Option<u32>> {
    let seconds: Option<i64> = sqlx::query_scalar("SELECT CEIL(EXTRACT(EPOCH FROM (MAX(cooldown_until)-clock_timestamp())))::bigint FROM llm_monthly_usage WHERE provider='gemini' AND cooldown_until>clock_timestamp()")
        .fetch_one(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(seconds.map(|s| s.clamp(0, 31536000) as u32))
}
async fn reserve_capped(
    connection: &mut PgConnection,
    provider: Provider,
    maximum: i32,
    pause: f64,
) -> Result<Month> {
    let mut transaction = connection
        .begin()
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    let result = reservation(&mut transaction, provider, maximum, pause).await;
    let month = match result {
        Ok(month) => {
            transaction
                .commit()
                .await
                .map_err(|_| Failure("provider_ledger_unavailable"))?;
            month
        }
        Err(error) => {
            // SQLx Drop queues ROLLBACK until the next use. Flush it now so a quiet
            // rejected caller cannot retain the ledger advisory lock indefinitely.
            transaction
                .rollback()
                .await
                .map_err(|_| Failure("provider_ledger_unavailable"))?;
            return Err(error);
        }
    };
    Ok(Month(month, provider))
}
async fn reservation(
    transaction: &mut Transaction<'_, Postgres>,
    provider: Provider,
    maximum: i32,
    pause: f64,
) -> Result<String> {
    sqlx::query("SELECT pg_advisory_xact_lock(166001,51)")
        .execute(&mut **transaction)
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    let paused:bool=sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM llm_monthly_usage WHERE provider=$1 AND cooldown_until>clock_timestamp())")
        .bind(provider.name()).fetch_one(&mut **transaction).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    if paused {
        return Err(Failure("rate_limited"));
    }
    sqlx::query_scalar(r#"
        INSERT INTO llm_monthly_usage
            (provider,month,requests,input_tokens,output_tokens,cooldown_until,created_at,updated_at)
        VALUES ($2,to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),1,0,0,
                clock_timestamp()+$3*interval '1 second',clock_timestamp(),clock_timestamp())
        ON CONFLICT (provider,month) DO UPDATE
        SET requests=llm_monthly_usage.requests+1,updated_at=clock_timestamp(),
            cooldown_until=clock_timestamp()+$3*interval '1 second'
        WHERE llm_monthly_usage.requests<$1
          AND (llm_monthly_usage.cooldown_until IS NULL
               OR llm_monthly_usage.cooldown_until<=clock_timestamp())
        RETURNING month
    "#).bind(maximum).bind(provider.name()).bind(pause)
        .fetch_optional(&mut **transaction).await
        .map_err(|_|Failure("provider_ledger_unavailable"))?
        .ok_or(Failure("monthly_request_limit"))
}

pub async fn tokens(
    connection: &mut PgConnection,
    month: &Month,
    input: Option<u32>,
    output: Option<u32>,
) -> Result<()> {
    sqlx::query("UPDATE llm_monthly_usage SET input_tokens=input_tokens+$1,output_tokens=output_tokens+$2,updated_at=clock_timestamp() WHERE provider=$4 AND month=$3")
        .bind(i64::from(input.unwrap_or(0))).bind(i64::from(output.unwrap_or(0))).bind(&month.0).bind(month.1.name()).execute(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(())
}
pub async fn cooldown(connection: &mut PgConnection, month: &Month, seconds: u32) -> Result<()> {
    let minimum = if matches!(month.1, Provider::Cohere) {
        60
    } else {
        0
    };
    sqlx::query("UPDATE llm_monthly_usage SET cooldown_until=GREATEST(COALESCE(cooldown_until,clock_timestamp()),clock_timestamp()+$1*interval '1 second'),updated_at=clock_timestamp() WHERE provider=$3 AND month=$2")
        .bind(f64::from(seconds.clamp(minimum,31536000))).bind(&month.0).bind(month.1.name()).execute(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(())
}

/// The optional local provider historically uses owner_preferences, not llm_monthly_usage.
/// Preserve all unknown JSON fields and fail closed on malformed existing counters.
pub(crate) async fn reserve_ollama(
    connection: &mut PgConnection,
    configured: u32,
) -> Result<String> {
    if configured > 10000 {
        return Err(Failure("invalid_provider_budget"));
    }
    if configured == 0 {
        return Err(Failure("monthly_request_limit"));
    }
    let mut tx = connection
        .begin()
        .await
        .map_err(|_| Failure("provider_ledger_unavailable"))?;
    let result=async {
        let key:String=sqlx::query_scalar("SELECT 'ai:ollama:'||to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM')").fetch_one(&mut *tx).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
        sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,'{\"requests\":0,\"cooldown\":0}',clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO NOTHING").bind(&key).execute(&mut *tx).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
        let mut value:serde_json::Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(&key).fetch_one(&mut *tx).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
        let requests=value["requests"].as_u64().ok_or(Failure("provider_ledger_invalid"))?;
        let cooldown=value.get("cooldown").map(|v|v.as_f64().filter(|v|v.is_finite() && *v>=0.0).ok_or(Failure("provider_ledger_invalid"))).transpose()?.unwrap_or(0.0);
        let now:f64=sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float8").fetch_one(&mut *tx).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
        if cooldown>now {return Err(Failure("rate_limited"));}
        if requests>=u64::from(configured.min(1000)) {return Err(Failure("monthly_request_limit"));}
        value["requests"]=serde_json::json!(requests+1);
        sqlx::query("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1").bind(&key).bind(value).execute(&mut *tx).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
        Ok(key)
    }.await;
    match result {
        Ok(key) => {
            tx.commit()
                .await
                .map_err(|_| Failure("provider_ledger_unavailable"))?;
            Ok(key)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("provider_ledger_unavailable"))?;
            Err(error)
        }
    }
}
pub(crate) async fn cooldown_ollama(connection: &mut PgConnection, key: &str) -> Result<()> {
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{cooldown}',to_jsonb(GREATEST(COALESCE((value->>'cooldown')::float8,0),EXTRACT(EPOCH FROM clock_timestamp())::float8+60))),updated_at=clock_timestamp() WHERE key=$1").bind(key).execute(connection).await.map_err(|_|Failure("provider_ledger_unavailable"))?;
    Ok(())
}
