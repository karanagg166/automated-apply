//! Atomic prepared lookup plus credit intent. Preparation confers no dispatch permission.
use super::*;
use sha2::{Digest, Sha256};
fn hash(raw: &str) -> String {
    format!("{:x}", Sha256::digest(raw.as_bytes()))
}
fn ack() -> Failure {
    Failure("contact_lookup_write_ack_failed")
}
#[derive(Clone, Copy)]
pub enum Target {
    Search,
    Contact(Uuid),
}
pub struct Claim {
    id: String,
    run_id: Uuid,
    provider: String,
    request: Value,
    target_version: String,
    reservation: Option<budget::Reservation>,
}
impl Claim {
    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn run_id(&self) -> Uuid {
        self.run_id
    }
    pub fn provider(&self) -> &str {
        &self.provider
    }
    pub fn request(&self) -> &Value {
        &self.request
    }
    pub fn target_version(&self) -> &str {
        &self.target_version
    }
    pub fn reservation(&self) -> Option<&budget::Reservation> {
        self.reservation.as_ref()
    }
}
pub fn domain(raw: &str) -> Option<String> {
    let raw = if raw.contains("://") {
        raw.to_owned()
    } else {
        format!("https://{raw}")
    };
    let safe = crate::resources::public_https(&raw)?;
    let url = reqwest::Url::parse(&safe).ok()?;
    let host = url.host_str()?;
    Some(
        host.strip_prefix("www.")
            .unwrap_or(host)
            .to_ascii_lowercase(),
    )
}
pub fn linkedin(raw: &str) -> Option<String> {
    let safe = crate::job_urls::canonical(raw).ok()?;
    let url = reqwest::Url::parse(&safe).ok()?;
    if !matches!(
        url.host_str(),
        Some(
            "linkedin.com"
                | "www.linkedin.com"
                | "in.linkedin.com"
                | "uk.linkedin.com"
                | "us.linkedin.com"
        )
    ) {
        return None;
    }
    let decoded = percent_encoding::percent_decode_str(url.path())
        .decode_utf8()
        .ok()?;
    let user = decoded.strip_prefix("/in/")?;
    if user.is_empty()
        || !user
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'%' | b'~' | b'-'))
    {
        return None;
    }
    Some(format!("https://www.linkedin.com{}/", url.path()))
}
async fn put_new(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(ack());
    }
    Ok(())
}
pub fn prefix(run: Uuid) -> String {
    format!("contact_lookup:{}:", run.simple())
}
pub async fn prepare(
    c: &mut PgConnection,
    run: &runs::Run,
    name: &str,
    target: Target,
    settings: &Settings,
    contacts_settings: &super::super::Settings,
) -> Result<Claim> {
    let provider = settings
        .providers
        .iter()
        .find(|p| p.name == name)
        .ok_or(Failure("invalid_contact_enrichment"))?;
    if run.input()["allow_paid"] != true {
        return Err(Failure("contact_paid_lookup_authorization_required"));
    }
    if !provider.enabled || !provider.credentials_configured {
        return Err(Failure("contact_provider_not_configured"));
    }
    let requested = run.input()["providers"].as_array().ok_or_else(invalid)?;
    let order = requested
        .iter()
        .position(|p| p == name)
        .ok_or(Failure("contact_provider_not_in_reviewed_plan"))?;
    let cost = if matches!(target, Target::Search) {
        0
    } else {
        provider.lookup_cost
    };
    if matches!(target, Target::Search) && (name != "apollo" || order != 0) {
        return Err(Failure("contact_search_not_in_reviewed_plan"));
    }
    if matches!(target, Target::Contact(_)) && cost == 0 {
        return Err(Failure("contact_lookup_cost_review_required"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    let company = runs::guard_in(&mut tx, run, settings).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let company_domain = company["domain"]
        .as_str()
        .and_then(domain)
        .ok_or(Failure("contact_company_domain_review_required"))?;
    let maximum = run.input()["max_people"]
        .as_i64()
        .ok_or_else(invalid)?
        .min(settings.max_people);
    let roles = run.input()["target_roles"].as_array().ok_or_else(invalid)?;
    let (operation, request, version, target_key) = match target {
        Target::Search => {
            let local = super::preview(
                &mut tx,
                run.company(),
                run.input(),
                settings,
                contacts_settings,
                now,
            )
            .await?;
            if local["contact_inventory_truncated"] == true
                || local["people_inventory_truncated"] == true
                || !local["cached_contacts"]
                    .as_array()
                    .is_some_and(Vec::is_empty)
                || !local["discovered_people"]
                    .as_array()
                    .is_some_and(Vec::is_empty)
            {
                return Err(Failure("contact_local_inventory_requires_review"));
            }
            (
                "search_people",
                json!({"company_id":run.company(),"company_domain":company_domain,"target_roles":roles,"max_people":maximum,"allow_paid":true}),
                hash(&company.to_string()),
                "search".to_owned(),
            )
        }
        Target::Contact(id) => {
            let contact: Value = sqlx::query_scalar(&format!(
                "SELECT {CONTACT} FROM contacts c WHERE c.id=$1 AND c.company_id=$3 FOR UPDATE"
            ))
            .bind(id)
            .bind(json!({}))
            .bind(run.company())
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
            .ok_or(Failure("contact_not_found"))?;
            rules::output(
                &contact,
                &super::super::company(&mut tx, run.company()).await?,
                None,
                contacts_settings,
                now,
            )?;
            if !policy::role_matches(contact["role_title"].as_str(), roles)
                || !policy::needs_lookup(&contact, contacts_settings.cache_days, now)
            {
                return Err(Failure("contact_lookup_not_needed"));
            }
            let profile = contact["linkedin_url"]
                .as_str()
                .and_then(linkedin)
                .ok_or(Failure("contact_professional_identifier_required"))?;
            let version = contact["review_version"]
                .as_str()
                .ok_or_else(invalid)?
                .to_owned();
            (
                "enrich_person",
                json!({"company_id":run.company(),"person_id":id,"company_domain":company_domain,"full_name":contact["full_name"],"linkedin_url":profile,"target_roles":roles,"max_people":1,"allow_paid":true}),
                version,
                id.to_string(),
            )
        }
    };
    let previous:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=32768 THEN value ELSE NULL END FROM owner_preferences WHERE starts_with(key,$1) ORDER BY key LIMIT 101").bind(prefix(run.id())).fetch_all(&mut *tx).await.map_err(db)?;
    let previous = previous
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    if previous.len() > 100 {
        return Err(Failure("contact_lookup_inventory_requires_review"));
    }
    let mut spent = 0i64;
    let mut people = BTreeSet::new();
    for intent in &previous {
        if intent["run_id"] != run.id().to_string()
            || intent["schema_version"] != 1
            || !matches!(intent["provider"].as_str(), Some("apollo" | "signalhire"))
            || intent["request"]["company_id"] != run.company().to_string()
        {
            return Err(invalid());
        }
        let amount = intent["estimated_cost"]
            .as_i64()
            .filter(|n| (0..=100).contains(n))
            .ok_or_else(invalid)?;
        if intent["provider"] == name {
            spent = spent.checked_add(amount).ok_or_else(invalid)?;
        }
        if let Some(person) = intent["request"]["person_id"].as_str() {
            people.insert(person.to_owned());
        }
    }
    if spent + cost > provider.per_run_limit {
        return Err(Failure("contact_provider_run_budget_exhausted"));
    }
    if matches!(target, Target::Contact(_))
        && !people.contains(&target_key)
        && people.len() >= maximum as usize
    {
        return Err(Failure("contact_run_person_limit_reached"));
    }
    if order > 0 {
        let prior = &requested[order - 1];
        if run.input()["allow_fallback"] != true
            || !previous.iter().any(|p| {
                p["provider"] == *prior
                    && p["target_key"] == target_key
                    && p["state"] == "observed"
                    && p["result_state"] == "completed"
                    && p["usable_profile_result"] == true
                    && p["missing_business_email"] == true
            })
        {
            return Err(Failure("contact_fallback_evidence_required"));
        }
    }
    let identity = if operation == "search_people" {
        crate::python_json::serialize(&run.input()["target_roles"], false, true)
    } else {
        request["linkedin_url"]
            .as_str()
            .ok_or_else(invalid)?
            .to_owned()
    };
    let identity_hash = hash(&format!("{operation}:{identity}"));
    let old:Option<Value>=sqlx::query_scalar("SELECT to_jsonb(l) FROM contact_provider_lookups l WHERE company_id=$1 AND provider=$2 AND identity_key=$3 FOR UPDATE").bind(run.company()).bind(name).bind(&identity_hash).fetch_optional(&mut *tx).await.map_err(db)?;
    if let Some(old) = &old {
        let expired = crate::gmail_history::contract::timestamp(&old["expires_at"])
            .is_some_and(|at| at.with_timezone(&Utc) < now);
        if !matches!(old["state"].as_str(), Some("completed" | "not_found")) || !expired {
            return Err(Failure("contact_lookup_already_claimed"));
        }
        put_new(
            &mut tx,
            &format!("cl_prior:{}", hash(&old.to_string())),
            old,
        )
        .await?;
    }
    let reservation_id = format!("contact_{}", Uuid::new_v4().simple());
    let reservation = if cost > 0 {
        Some(
            budget::reserve_in(&mut tx, name, &reservation_id, cost, provider.monthly_limit)
                .await?,
        )
    } else {
        None
    };
    // Zero-credit search still respects all-month cooldowns and the non-replayable claim.
    if cost==0&&sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider=$1 AND cooldown_until>$2)").bind(name).bind(now).fetch_one(&mut *tx).await.map_err(db)?{return Err(Failure("contact_provider_cooling_down"));}
    let id = old
        .as_ref()
        .and_then(|v| v["id"].as_str())
        .and_then(|s| s.parse::<Uuid>().ok())
        .unwrap_or_else(Uuid::new_v4);
    let expires = now + chrono::Duration::days(contacts_settings.cache_days);
    let written: Option<Value> = if let Some(old) = old {
        sqlx::query_scalar("UPDATE contact_provider_lookups SET reservation_id=$2,state='running',expires_at=$3 WHERE id=$1 AND reservation_id=$4 AND state=$5 RETURNING jsonb_build_object('id',id,'company_id',company_id,'provider',provider,'identity_key',identity_key,'reservation_id',reservation_id,'state',state,'expiry_exact',expires_at=$3)").bind(id).bind(&reservation_id).bind(expires).bind(old["reservation_id"].as_str()).bind(old["state"].as_str()).fetch_optional(&mut *tx).await.map_err(db)?
    } else {
        sqlx::query_scalar("INSERT INTO contact_provider_lookups(id,company_id,provider,identity_key,reservation_id,state,expires_at) VALUES($1,$2,$3,$4,$5,'running',$6) RETURNING jsonb_build_object('id',id,'company_id',company_id,'provider',provider,'identity_key',identity_key,'reservation_id',reservation_id,'state',state,'expiry_exact',expires_at=$6)").bind(id).bind(run.company()).bind(name).bind(&identity_hash).bind(&reservation_id).bind(expires).fetch_optional(&mut *tx).await.map_err(db)?
    };
    if written
        != Some(
            json!({"id":id,"company_id":run.company(),"provider":name,"identity_key":identity_hash,"reservation_id":reservation_id,"state":"running","expiry_exact":true}),
        )
    {
        return Err(ack());
    }
    let intent = json!({"schema_version":1,"run_id":run.id(),"lookup_id":id,"provider":name,"operation":operation,"identity_key":identity_hash,"reservation_id":reservation_id,"estimated_cost":cost,"state":"prepared","post_admissions":0,"request":request,"target_key":target_key,"target_version":version,"dispatch_deadline":run.deadline(),"prepared_at":now,"dispatch_authorized":false});
    put_new(
        &mut tx,
        &format!("{}{reservation_id}", prefix(run.id())),
        &intent,
    )
    .await?;
    tx.commit()
        .await
        .map_err(|_| Failure("contact_lookup_commit_outcome_unknown"))?;
    Ok(Claim {
        id: reservation_id,
        run_id: run.id(),
        provider: name.into(),
        request,
        target_version: version,
        reservation,
    })
}
