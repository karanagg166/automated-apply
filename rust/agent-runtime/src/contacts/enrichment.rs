//! Local enrichment planning and saved records. This module never dispatches provider IO.
use super::*;
pub mod budget;
pub mod capabilities;
pub mod contract;
pub mod lookups;
pub mod person;
pub mod policy;
pub mod runs;
pub struct Provider {
    pub name: &'static str,
    pub enabled: bool,
    pub credentials_configured: bool,
    pub monthly_limit: i64,
    pub per_run_limit: i64,
    pub lookup_cost: i64,
}
pub struct Settings {
    pub providers: [Provider; 2],
    pub max_people: i64,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let integer = |key: &str, default: &str, min: i64, max: i64| -> Result<i64> {
            values
                .get(key)
                .map(String::as_str)
                .unwrap_or(default)
                .parse::<i64>()
                .ok()
                .filter(|n| (min..=max).contains(n))
                .ok_or(Failure("invalid_contact_provider_settings"))
        };
        let provider = |name: &'static str, monthly: &str, cap: &str| -> Result<Provider> {
            let prefix = name.to_ascii_uppercase();
            let enabled = match values
                .get(&format!("{prefix}_ENRICHMENT_ENABLED"))
                .map(String::as_str)
                .unwrap_or("false")
                .to_ascii_lowercase()
                .as_str()
            {
                "true" | "1" | "yes" | "on" | "y" | "t" => true,
                "false" | "0" | "no" | "off" | "n" | "f" => false,
                _ => return Err(Failure("invalid_contact_provider_settings")),
            };
            Ok(Provider {
                name,
                enabled,
                credentials_configured: values
                    .get(&format!("{prefix}_API_KEY"))
                    .is_some_and(|s| !s.trim().is_empty()),
                monthly_limit: integer(&format!("{prefix}_MONTHLY_LIMIT"), monthly, 0, i64::MAX)?,
                per_run_limit: integer(&format!("{prefix}_PER_RUN_LIMIT"), cap, 0, 100)?,
                lookup_cost: integer(&format!("{prefix}_CREDITS_PER_LOOKUP"), "0", 0, 100)?,
            })
        };
        Ok(Self {
            providers: [
                provider("apollo", "50", "5")?,
                provider("signalhire", "5", "2")?,
            ],
            max_people: integer("CONTACT_ENRICHMENT_MAX_PEOPLE_PER_RUN", "10", 1, 25)?,
        })
    }
}
#[derive(Clone, Copy)]
pub enum Route {
    Providers,
    Preview(Uuid),
    Run(Uuid),
}
impl Route {
    pub fn method(self) -> &'static str {
        if matches!(self, Self::Preview(_)) {
            "POST"
        } else {
            "GET"
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    if path == "/api/v1/contact-enrichment/providers" {
        return Some(Route::Providers);
    }
    if let Some(id) = path.strip_prefix("/api/v1/contact-enrichment/runs/") {
        return id.parse().ok().map(Route::Run);
    }
    path.strip_prefix("/api/v1/companies/")
        .and_then(|s| s.strip_suffix("/contacts/preview"))
        .and_then(|s| s.parse().ok())
        .map(Route::Preview)
}
pub fn provider_status(provider: &Provider, budget: Option<&Value>) -> Result<Value> {
    let reserved = match budget {
        Some(b) => b["reserved"]
            .as_f64()
            .filter(|n| n.is_finite() && *n >= 0.0)
            .ok_or_else(invalid)?,
        None => 0.0,
    };
    let configured = provider.enabled && provider.credentials_configured;
    Ok(
        json!({"provider":provider.name,"enabled":provider.enabled,"credentials_configured":provider.credentials_configured,"configuration_status":if configured{"completed"}else{"not_configured"},"capabilities":{"search_people":provider.name=="apollo","enrich_person":true,"get_usage":provider.name=="signalhire","test_connection":true,"bulk":false,"mailbox_verification":false,"delivery":"synchronous"},"budget":{"monthly_limit":provider.monthly_limit,"reserved_estimate":reserved,"remaining_local_budget":(provider.monthly_limit as f64-reserved).max(0.0),"provider_balance":null,"credits_per_lookup_estimate":if provider.lookup_cost==0{None}else{Some(provider.lookup_cost)},"per_run_limit":provider.per_run_limit,"cooldown_until":budget.map(|b|b["cooldown_until"].clone()).unwrap_or(Value::Null)},"live_verification":"not_checked","billing_configuration_required":provider.lookup_cost==0,"native_lookup_execution_ready":false}),
    )
}
async fn providers(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let month = now.format("%Y-%m").to_string();
    let budgets:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('provider',provider,'reserved',reserved,'cooldown_until',cooldown_until) FROM discovery_monthly_budgets WHERE provider IN ('apollo','signalhire') AND month=$1 ORDER BY provider").bind(month).fetch_all(&mut **tx).await.map_err(db)?;
    let mut result = Vec::new();
    for provider in &settings.providers {
        let found = budgets
            .iter()
            .filter(|b| b["provider"] == provider.name)
            .collect::<Vec<_>>();
        if found.len() > 1 {
            return Err(invalid());
        }
        result.push(provider_status(provider, found.first().copied())?);
    }
    Ok(
        json!({"providers":result,"record_basis":"saved_local_budget_and_operator_configuration","provider_requests":0}),
    )
}
async fn preview(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    input: &Value,
    settings: &Settings,
    contacts_settings: &super::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let company = super::company(tx, id).await?;
    let domain: Option<String> = sqlx::query_scalar("SELECT domain FROM companies WHERE id=$1")
        .bind(id)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let mut contacts: Vec<Value> = sqlx::query_scalar(&format!(
        "SELECT {CONTACT} FROM contacts c WHERE c.company_id=$1 ORDER BY c.id LIMIT 1001"
    ))
    .bind(id)
    .bind(json!({}))
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let contacts_truncated = contacts.len() > 1000;
    contacts.truncate(1000);
    let mut people:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name,'role',role,'linkedin_url',CASE WHEN octet_length(linkedin_url)<=2048 THEN linkedin_url ELSE NULL END) FROM discovered_company_people WHERE company_id=$1 ORDER BY observed_at DESC,id LIMIT 101").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
    let people_truncated = people.len() > 100;
    people.truncate(100);
    let roles = input["target_roles"].as_array().ok_or_else(invalid)?;
    let mut selected = Vec::new();
    for contact in contacts {
        rules::output(&contact, &company, None, contacts_settings, now)?;
        if policy::role_matches(contact["role_title"].as_str(), roles) {
            selected.push(contact);
        }
    }
    people.retain(|p| policy::role_matches(p["role"].as_str(), roles));
    let targets = selected
        .iter()
        .filter(|c| policy::needs_lookup(c, contacts_settings.cache_days, now))
        .collect::<Vec<_>>();
    let unmapped = people
        .iter()
        .filter(|p| {
            p["name"].as_str().is_some_and(|s| !s.is_empty())
                && !selected
                    .iter()
                    .any(|c| c["linkedin_url"] == p["linkedin_url"])
        })
        .collect::<Vec<_>>();
    let maximum = input["max_people"]
        .as_i64()
        .ok_or_else(invalid)?
        .min(settings.max_people);
    let requested = input["providers"].as_array().ok_or_else(invalid)?;
    let empty = selected.is_empty() && people.is_empty();
    let count = if empty
        && domain.as_ref().is_some_and(|s| !s.is_empty())
        && requested.first() == Some(&json!("apollo"))
    {
        maximum
    } else {
        maximum.min((targets.len() + unmapped.len()) as i64)
    };
    let plan=requested.iter().map(|name|{
        let provider=settings.providers.iter().find(|p|name==p.name).ok_or_else(invalid)?;
        Ok(json!({"provider":name,"lookup_count_upper_bound":count,"reserved_credit_upper_bound":if provider.lookup_cost==0{None}else{Some((count*provider.lookup_cost).min(provider.per_run_limit))},"cost_basis":"operator_configured_account_estimate","configured":provider.enabled&&provider.credentials_configured,"billable_authorization_present":input["allow_paid"],"fallback_requires_opt_in":requested.first()!=Some(name),"search_if_no_targets":provider.name=="apollo"&&empty&&domain.as_ref().is_some_and(|s|!s.is_empty()),"search_credits":if provider.name=="apollo"{Some(0)}else{None},"live_eligibility_verified":false}))
    }).collect::<Result<Vec<_>>>()?;
    let evidence:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'source',source,'type',evidence_type,'url',CASE WHEN octet_length(evidence_url)<=2048 THEN evidence_url ELSE NULL END,'collected_at',collected_at,'provenance',jsonb_strip_nulls(jsonb_build_object('email',provenance::jsonb->'email','email_kind',provenance::jsonb->'email_kind','full_name',provenance::jsonb->'full_name','requires_review',provenance::jsonb->'requires_review'))) FROM contact_evidence WHERE company_id=$1 AND contact_id IS NULL AND expires_at>$2 ORDER BY collected_at DESC,id LIMIT 100").bind(id).bind(now).fetch_all(&mut **tx).await.map_err(db)?;
    let evidence = evidence
        .into_iter()
        .map(|mut e| {
            let provenance = e["provenance"].as_object().ok_or_else(invalid)?;
            for (key, max) in [("email", 255), ("full_name", 255), ("email_kind", 50)] {
                if provenance
                    .get(key)
                    .is_some_and(|v| v.as_str().is_none_or(|s| s.chars().count() > max))
                {
                    return Err(invalid());
                }
            }
            if provenance
                .get("requires_review")
                .is_some_and(|v| !v.is_boolean())
            {
                return Err(invalid());
            }
            e["url"] = e["url"]
                .as_str()
                .and_then(crate::resources::public_https)
                .map(|s| json!(s))
                .unwrap_or(Value::Null);
            if e.to_string().len() > 16384 {
                return Err(invalid());
            }
            Ok(e)
        })
        .collect::<Result<Vec<_>>>()?;
    let mut discovered = Vec::new();
    for p in &people {
        let mut p = p.clone();
        p["linkedin_url"] = p["linkedin_url"]
            .as_str()
            .and_then(crate::resources::public_https)
            .map(|s| json!(s))
            .unwrap_or(Value::Null);
        discovered.push(p);
    }
    Ok(
        json!({"company_id":id,"company_evidence":evidence,"cached_contacts":selected.iter().take(100).map(|c|json!({"id":c["id"],"name":c["full_name"],"role":c["role_title"],"email_status":c["email_status"]})).collect::<Vec<_>>(),"discovered_people":discovered,"targets":targets.iter().take(maximum as usize).map(|c|c["id"].clone()).collect::<Vec<_>>(),"discovered_targets":unmapped.iter().take(maximum as usize).map(|p|p["id"].clone()).collect::<Vec<_>>(),"no_lookup_needed":selected.iter().filter(|c|!policy::needs_lookup(c,contacts_settings.cache_days,now)).take(100).map(|c|c["id"].clone()).collect::<Vec<_>>(),"provider_plan":plan,"max_people":maximum,"read_only":true,"billable_calls":0,"provider_requests":0,"contact_inventory_truncated":contacts_truncated,"people_inventory_truncated":people_truncated,"live_eligibility_verified":false}),
    )
}
async fn run(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(target_roles::text)+octet_length(provider_plan::text)+octet_length(contact_ids::text)+octet_length(counts::text)+octet_length(usage::text)+octet_length(errors::text)<=262144 THEN jsonb_build_object('id',id,'company_id',company_id,'state',state,'target_roles',target_roles,'provider_plan',provider_plan,'contact_ids',contact_ids,'counts',counts,'usage',usage,'errors',errors,'started_at',started_at,'completed_at',completed_at) ELSE NULL END FROM contact_enrichment_runs WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("contact_enrichment_run_not_found"))?;
    policy::saved_run(value.ok_or_else(invalid)?)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
    contacts_settings: &super::Settings,
) -> Result<Value> {
    if route.method() != method {
        return Err(Failure("contact_method_not_allowed"));
    }
    if query.is_some() || method == "GET" && !body.is_empty() {
        return Err(Failure("invalid_contact_query"));
    }
    let input = if matches!(route, Route::Preview(_)) {
        Some(contract::normalize(
            serde_json::from_slice(body).map_err(|_| Failure("invalid_contact_enrichment"))?,
        )?)
    } else {
        None
    };
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let result = match route {
        Route::Providers => providers(&mut tx, settings, now).await?,
        Route::Run(id) => run(&mut tx, id).await?,
        Route::Preview(id) => {
            preview(
                &mut tx,
                id,
                input.as_ref().unwrap(),
                settings,
                contacts_settings,
                now,
            )
            .await?
        }
    };
    tx.commit()
        .await
        .map_err(|_| Failure("contact_commit_outcome_unknown"))?;
    Ok(result)
}
