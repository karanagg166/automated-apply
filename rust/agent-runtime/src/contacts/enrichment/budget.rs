//! Durable credit accounting only. A reservation is not provider entitlement or dispatch proof.
use super::*;
fn ack() -> Failure {
    Failure("contact_budget_write_ack_failed")
}
fn invalid_budget() -> Failure {
    Failure("invalid_contact_budget")
}
fn valid_provider(provider: &str) -> Result<()> {
    if matches!(provider, "apollo" | "signalhire") {
        Ok(())
    } else {
        Err(invalid_budget())
    }
}
fn valid_id(id: &str) -> Result<()> {
    if id.len() <= 100
        && id.starts_with("contact_")
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
    {
        Ok(())
    } else {
        Err(invalid_budget())
    }
}
async fn transaction(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("contact_budget_commit_outcome_unknown"))
}
/// The fields deliberately have no Debug/Serialize implementation and confer no remote grant.
pub struct Reservation {
    id: String,
    provider: String,
    month: String,
    amount: i64,
}
impl Reservation {
    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn provider(&self) -> &str {
        &self.provider
    }
    pub fn month(&self) -> &str {
        &self.month
    }
    pub fn amount(&self) -> i64 {
        self.amount
    }
}
pub async fn reserve(
    c: &mut PgConnection,
    provider: &str,
    id: &str,
    amount: i64,
    maximum: i64,
) -> Result<Reservation> {
    valid_provider(provider)?;
    valid_id(id)?;
    if !(1..=100).contains(&amount) || maximum < amount || maximum > 9_999_999_999 {
        return Err(invalid_budget());
    }
    let mut tx = transaction(c).await?;
    let now = clock(&mut tx).await?;
    let month = now.format("%Y-%m").to_string();
    if sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS(SELECT 1 FROM discovery_budget_reservations WHERE id=$1)",
    )
    .bind(id)
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?
    {
        return Err(Failure("contact_reservation_already_used"));
    }
    let cooling:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider=$1 AND cooldown_until>$2)").bind(provider).bind(now).fetch_one(&mut *tx).await.map_err(db)?;
    if cooling {
        return Err(Failure("contact_provider_cooling_down"));
    }
    let previous:Option<(String,bool,bool,Option<DateTime<Utc>>)>=sqlx::query_as("SELECT reserved::text,reserved>=0,reserved+$3::numeric<=$4::numeric,cooldown_until FROM discovery_monthly_budgets WHERE provider=$1 AND month=$2 FOR UPDATE").bind(provider).bind(&month).bind(amount.to_string()).bind(maximum.to_string()).fetch_optional(&mut *tx).await.map_err(db)?;
    if let Some((_, nonnegative, fits, _)) = &previous {
        if !nonnegative {
            return Err(invalid_budget());
        }
        if !fits {
            return Err(Failure("contact_provider_budget_exhausted"));
        }
    }
    let written:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_budget_reservations(id,provider,month,reserved,provider_run_id,reported_actual,state,created_at) VALUES($1,$2,$3,$4::numeric,NULL,NULL,'reserved',$5) ON CONFLICT(id) DO NOTHING RETURNING jsonb_build_object('id',id,'provider',provider,'month',month,'amount_exact',reserved=$4::numeric,'provider_run_id',provider_run_id,'reported_actual',reported_actual,'state',state,'created_at_exact',created_at=$5)").bind(id).bind(provider).bind(&month).bind(amount.to_string()).bind(now).fetch_optional(&mut *tx).await.map_err(db)?;
    if written
        != Some(
            json!({"id":id,"provider":provider,"month":month,"amount_exact":true,"provider_run_id":null,"reported_actual":null,"state":"reserved","created_at_exact":true}),
        )
    {
        return Err(ack());
    }
    let accepted: Option<bool> = if let Some((before, _, _, cooldown)) = previous {
        sqlx::query_scalar("UPDATE discovery_monthly_budgets SET reserved=round(reserved+$3::numeric,6) WHERE provider=$1 AND month=$2 AND reserved=$4::numeric AND reserved+$3::numeric<=$5::numeric AND (cooldown_until IS NULL OR cooldown_until<=$6) RETURNING provider=$1 AND month=$2 AND reserved=round($4::numeric+$3::numeric,6) AND cooldown_until IS NOT DISTINCT FROM $7").bind(provider).bind(&month).bind(amount.to_string()).bind(before).bind(maximum.to_string()).bind(now).bind(cooldown).fetch_optional(&mut *tx).await.map_err(db)?
    } else {
        sqlx::query_scalar("INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES($1,$2,$3::numeric,NULL) RETURNING reserved=$3::numeric AND cooldown_until IS NULL AND provider=$1 AND month=$2").bind(provider).bind(&month).bind(amount.to_string()).fetch_optional(&mut *tx).await.map_err(db)?
    };
    if accepted != Some(true) {
        return Err(ack());
    }
    commit(tx).await?;
    Ok(Reservation {
        id: id.into(),
        provider: provider.into(),
        month,
        amount,
    })
}
fn terminal(state: &str) -> bool {
    matches!(
        state,
        "completed"
            | "not_found"
            | "rate_limited"
            | "budget_exhausted"
            | "failed"
            | "unsupported_operation"
            | "billing_uncertain"
            | "authorization_required"
            | "queued"
            | "running"
    )
}
/// Never subtracts reserved credits. Identical repeat findings return without another write.
pub async fn finish(
    c: &mut PgConnection,
    reservation: &Reservation,
    state: &str,
    actual: Option<i64>,
    provider_run: Option<&str>,
) -> Result<Value> {
    if !terminal(state)
        || actual.is_some_and(|n| !(0..=9_999_999_999).contains(&n))
        || provider_run
            .is_some_and(|s| s.is_empty() || s.len() > 255 || s.chars().any(char::is_control))
    {
        return Err(invalid_budget());
    }
    let mut tx = transaction(c).await?;
    let before:Value=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'provider',provider,'month',month,'amount_exact',reserved=$2::numeric,'provider_run_id',provider_run_id,'reported_actual',reported_actual::text,'state',state,'created_at',created_at) FROM discovery_budget_reservations WHERE id=$1 FOR UPDATE").bind(&reservation.id).bind(reservation.amount.to_string()).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("contact_reservation_not_found"))?;
    if before["provider"] != reservation.provider
        || before["month"] != reservation.month
        || before["amount_exact"] != true
    {
        return Err(invalid_budget());
    }
    let actual_text = actual.map(|n| format!("{n}.000000"));
    if before["state"] != "reserved" {
        if before["state"] != state
            || before["provider_run_id"] != json!(provider_run)
            || before["reported_actual"] != json!(actual_text)
        {
            return Err(Failure("contact_reservation_terminal_conflict"));
        }
        commit(tx).await?;
        return Ok(
            json!({"reservation_id":reservation.id,"state":state,"reserved_credits":reservation.amount,"reported_actual":actual,"provider_run_id":provider_run,"accounting":"full_cap_retained","record_basis":"retained_budget_finding"}),
        );
    }
    if !before["provider_run_id"].is_null() || !before["reported_actual"].is_null() {
        return Err(Failure("contact_reservation_terminal_conflict"));
    }
    let mut expected = before.clone();
    expected["state"] = json!(state);
    expected["provider_run_id"] = json!(provider_run);
    expected["reported_actual"] = json!(actual_text);
    let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_budget_reservations SET state=$2,reported_actual=$3::numeric,provider_run_id=$4 WHERE id=$1 AND state='reserved' RETURNING jsonb_build_object('id',id,'provider',provider,'month',month,'amount_exact',reserved=$5::numeric,'provider_run_id',provider_run_id,'reported_actual',reported_actual::text,'state',state,'created_at',created_at)").bind(&reservation.id).bind(state).bind(actual.map(|n|n.to_string())).bind(provider_run).bind(reservation.amount.to_string()).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    commit(tx).await?;
    Ok(
        json!({"reservation_id":reservation.id,"state":state,"reserved_credits":reservation.amount,"reported_actual":actual,"provider_run_id":provider_run,"accounting":"full_cap_retained","record_basis":"recorded_budget_finding"}),
    )
}
/// Provider cooldowns are monotonic and survive a month boundary.
pub async fn cooldown(c: &mut PgConnection, provider: &str, seconds: i64) -> Result<Value> {
    valid_provider(provider)?;
    if !(1..=86400).contains(&seconds) {
        return Err(invalid_budget());
    }
    let mut tx = transaction(c).await?;
    let now = clock(&mut tx).await?;
    let until = now + chrono::Duration::seconds(seconds);
    let month = now.format("%Y-%m").to_string();
    let existing:Vec<(String,String,Option<DateTime<Utc>>)>=sqlx::query_as("SELECT month,reserved::text,cooldown_until FROM discovery_monthly_budgets WHERE provider=$1 ORDER BY month LIMIT 121 FOR UPDATE").bind(provider).fetch_all(&mut *tx).await.map_err(db)?;
    if existing.len() > 120
        || existing.iter().any(|(m, amount, _)| {
            chrono::NaiveDate::parse_from_str(&format!("{m}-01"), "%Y-%m-%d").is_err()
                || amount.starts_with('-')
        })
    {
        return Err(Failure("contact_budget_inventory_requires_review"));
    }
    let mut expected = existing
        .into_iter()
        .map(|(m, amount, old)| (m, (amount, old.unwrap_or(until).max(until))))
        .collect::<BTreeMap<_, _>>();
    if !expected.contains_key(&month) {
        if expected.len() >= 120 {
            return Err(Failure("contact_budget_inventory_requires_review"));
        }
        let inserted:Option<bool>=sqlx::query_scalar("INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES($1,$2,0,NULL) RETURNING provider=$1 AND month=$2 AND reserved=0 AND cooldown_until IS NULL").bind(provider).bind(&month).fetch_optional(&mut *tx).await.map_err(db)?;
        if inserted != Some(true) {
            return Err(ack());
        }
        expected.insert(month, ("0.000000".into(), until));
    }
    let months = expected.keys().cloned().collect::<Vec<_>>();
    let saved:Vec<(String,String,DateTime<Utc>,String)>=sqlx::query_as("UPDATE discovery_monthly_budgets SET cooldown_until=greatest(coalesce(cooldown_until,$3),$3) WHERE provider=$1 AND month=ANY($2) RETURNING month,reserved::text,cooldown_until,provider").bind(provider).bind(&months).bind(until).fetch_all(&mut *tx).await.map_err(db)?;
    if saved.len() != expected.len()
        || saved.iter().any(|(m, amount, deadline, p)| {
            p != provider || expected.get(m) != Some(&(amount.clone(), *deadline))
        })
    {
        return Err(ack());
    }
    commit(tx).await?;
    Ok(
        json!({"provider":provider,"minimum_cooldown_until":until,"months_updated":months.len(),"credits_refunded":0}),
    )
}
