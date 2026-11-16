//! Pure Apollo metadata/eligibility checks. These functions do not call or authenticate a provider.
use super::*;
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Operation {
    Search,
    Enrich,
}
impl Operation {
    pub fn endpoint(self) -> &'static str {
        match self {
            Self::Search => "api/v1/mixed_people/api_search",
            Self::Enrich => "api/v1/people/match",
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Search => "search_people",
            Self::Enrich => "enrich_person",
        }
    }
}
fn missing() -> Failure {
    Failure("contact_apollo_capability_evidence_required")
}
fn allowance(value: &Value) -> Result<u64> {
    // JSON floating values and booleans do not establish integral account allowances.
    match value {
        Value::Number(n) if !n.is_f64() => n.as_u64().ok_or_else(missing),
        _ => Err(missing()),
    }
}
fn balance(row: &Value) -> Result<Value> {
    let limit = allowance(&row["limit"])?;
    let consumed = allowance(&row["consumed"])?;
    let left = allowance(&row["left_over"])?;
    if consumed > limit || left > limit - consumed {
        return Err(missing());
    }
    Ok(json!({"limit":limit,"consumed":consumed,"remaining":left}))
}
pub fn endpoint_limits(payload: &Value, endpoint: &str) -> Result<Value> {
    let rows = payload.as_object().ok_or_else(missing)?;
    if rows.len() > 10000 {
        return Err(missing());
    }
    let mut matches = Vec::new();
    for (key, value) in rows {
        if key.len() > 2048 {
            return Err(missing());
        }
        let same = if key == endpoint {
            true
        } else {
            serde_json::from_str::<Vec<String>>(key)
                .ok()
                .is_some_and(|parts| parts.join("/") == endpoint)
        };
        if same {
            matches.push(value);
        }
    }
    if matches.len() != 1 || !matches[0].is_object() {
        return Err(missing());
    }
    let mut output = serde_json::Map::new();
    for period in ["minute", "hour", "day"] {
        output.insert(period.into(), balance(&matches[0][period])?);
    }
    Ok(Value::Object(output))
}
pub fn credit_balance(payload: &Value, pool: &str) -> Result<Value> {
    if pool.is_empty() || pool.len() > 100 || !payload.is_object() {
        return Err(missing());
    }
    let root = payload.get(pool);
    let wrapper = payload.get("credit_usage_stats");
    if wrapper.is_some_and(|w| !w.is_object()) {
        return Err(missing());
    }
    let nested = wrapper.and_then(|w| w.get(pool));
    let row = match (root, nested) {
        (Some(row), None) if wrapper.is_none() => row,
        (None, Some(row)) => row,
        _ => return Err(missing()),
    };
    let mut result = balance(row)?;
    result["pool"] = json!(pool);
    Ok(result)
}
pub struct Eligibility {
    free_account_confirmed: bool,
    work_email_confirmed: bool,
    reviewed_at: Option<DateTime<Utc>>,
    evidence_url: Option<String>,
    endpoints: Vec<String>,
    pub pool: Option<String>,
}
impl Eligibility {
    pub(super) fn deadline(
        &self,
        operation: Operation,
        now: DateTime<Utc>,
    ) -> Result<DateTime<Utc>> {
        self.require(operation, now)?;
        self.reviewed_at
            .map(|at| at + chrono::Duration::hours(24))
            .ok_or(Failure("contact_apollo_eligibility_review_required"))
    }
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let flag = |name: &str| -> Result<bool> {
            match values
                .get(name)
                .map(String::as_str)
                .unwrap_or("false")
                .to_ascii_lowercase()
                .as_str()
            {
                "true" | "1" | "yes" | "on" | "y" | "t" => Ok(true),
                "false" | "0" | "no" | "off" | "n" | "f" => Ok(false),
                _ => Err(Failure("invalid_contact_provider_settings")),
            }
        };
        let reviewed_at = values
            .get("APOLLO_ELIGIBILITY_REVIEWED_AT")
            .filter(|s| !s.is_empty())
            .map(|s| {
                crate::gmail_history::contract::timestamp(&json!(s))
                    .map(|d| d.with_timezone(&Utc))
                    .or_else(|| rules::timestamp(&json!(s)))
                    .ok_or(Failure("invalid_contact_provider_settings"))
            })
            .transpose()?;
        let endpoints = values
            .get("APOLLO_REVIEWED_ENDPOINTS")
            .map(|s| {
                serde_json::from_str::<Vec<String>>(s)
                    .map_err(|_| Failure("invalid_contact_provider_settings"))
            })
            .transpose()?
            .unwrap_or_default();
        if endpoints.len() > 20 || endpoints.iter().any(|s| s.len() > 255) {
            return Err(Failure("invalid_contact_provider_settings"));
        }
        Ok(Self {
            free_account_confirmed: flag("APOLLO_FREE_ACCOUNT_CONFIRMED")?,
            work_email_confirmed: flag("APOLLO_WORK_EMAIL_CONFIRMED")?,
            reviewed_at,
            evidence_url: values
                .get("APOLLO_ELIGIBILITY_EVIDENCE_URL")
                .and_then(|s| crate::resources::public_https(s)),
            endpoints,
            pool: values
                .get("APOLLO_CREDIT_POOL")
                .filter(|s| !s.is_empty() && s.len() <= 100)
                .cloned(),
        })
    }
    pub fn require(&self, operation: Operation, now: DateTime<Utc>) -> Result<()> {
        if !self.free_account_confirmed
            || !self.work_email_confirmed
            || self.evidence_url.is_none()
            || !self.endpoints.iter().any(|s| s == operation.endpoint())
            || !self
                .reviewed_at
                .is_some_and(|at| at <= now && at >= now - chrono::Duration::hours(24))
        {
            return Err(Failure("contact_apollo_eligibility_review_required"));
        }
        Ok(())
    }
}
/// Coherent metadata is a necessary condition. Caller still needs current settings,
/// an owner-approved request, durable intent/credit admission and exact target identity.
pub fn preflight(
    eligibility: &Eligibility,
    operation: Operation,
    health: &Value,
    stats: &Value,
    credits: &Value,
    cost: i64,
    now: DateTime<Utc>,
) -> Result<Value> {
    eligibility.require(operation, now)?;
    if !(0..=100).contains(&cost) || health["healthy"] != true || health["is_logged_in"] != true {
        return Err(missing());
    }
    let rates = endpoint_limits(stats, operation.endpoint())?;
    let credits = credit_balance(credits, eligibility.pool.as_deref().ok_or_else(missing)?)?;
    if rates
        .as_object()
        .unwrap()
        .values()
        .any(|row| row["remaining"].as_u64() == Some(0))
    {
        return Err(Failure("contact_provider_cooling_down"));
    }
    if credits["remaining"].as_u64().ok_or_else(missing)? < (cost as u64) {
        return Err(Failure("contact_provider_budget_exhausted"));
    }
    Ok(
        json!({"provider":"apollo","operation":operation.name(),"endpoint":operation.endpoint(),"rate_limits":rates,"credits":credits,"eligibility_review_current":true,"provider_requests_performed":0,"lookup_authorized":false,"paid_upgrade_authorized":false}),
    )
}
