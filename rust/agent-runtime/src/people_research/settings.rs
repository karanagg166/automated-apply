//! Explicit saved rights and local request limits; not provider balance or live entitlement.
use crate::{Failure, Result};
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub struct Settings {
    pub(super) enabled: bool,
    pub(super) key: Option<String>,
    pub(super) reviewed: bool,
    pub(super) permission: Option<String>,
    pub(super) profiles: bool,
    pub(super) domains: BTreeMap<String, String>,
    pub(super) monthly: i64,
    pub(super) context: String,
}
fn invalid() -> Failure {
    Failure("invalid_public_research_settings")
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let key = values
            .get("SERPER_API_KEY")
            .filter(|v| !v.trim().is_empty())
            .cloned();
        if key
            .as_ref()
            .is_some_and(|v| v.len() > 4096 || !v.bytes().all(|b| (33..=126).contains(&b)))
        {
            return Err(invalid());
        }
        let permission = values
            .get("PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL")
            .filter(|v| !v.trim().is_empty())
            .map(|v| crate::resources::public_https(v).ok_or_else(invalid))
            .transpose()?;
        let raw = values
            .get("PUBLIC_SEARCH_ALLOWED_DOMAINS")
            .map(String::as_str)
            .unwrap_or("{}");
        if raw.len() > 65536 {
            return Err(invalid());
        }
        let domains: BTreeMap<String, String> = serde_json::from_str(raw).map_err(|_| invalid())?;
        if domains.len() > 100 {
            return Err(invalid());
        }
        let domains = domains
            .into_iter()
            .map(|(domain, url)| {
                if crate::contacts::enrichment::person::identity_domain(&domain).as_deref()
                    != Some(domain.as_str())
                {
                    return Err(invalid());
                }
                Ok((
                    domain,
                    crate::resources::public_https(&url).ok_or_else(invalid)?,
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        let flag = |name| crate::configuration::boolean(values, name, false).map_err(|_| invalid());
        let monthly = values
            .get("SERPER_MONTHLY_LIMIT")
            .map(String::as_str)
            .unwrap_or("100")
            .parse::<i64>()
            .ok()
            .filter(|n| (0..=9_999_999_999).contains(n))
            .ok_or_else(invalid)?;
        let enabled = flag("PEOPLE_SEARCH_ENABLED")?;
        let reviewed = flag("PUBLIC_SEARCH_RIGHTS_REVIEWED")?;
        let profiles = flag("LINKEDIN_SEARCH_RETENTION_AUTHORIZED")?;
        let key_hash = key.as_ref().map(|k| {
            use sha2::{Digest, Sha256};
            format!("{:x}", Sha256::digest(k.as_bytes()))
        });
        let context = crate::startup_catalog::identity::content_hash(
            &json!({"enabled":enabled,"key_hash":key_hash,"reviewed":reviewed,"permission":permission,"profiles":profiles,"domains":domains,"monthly":monthly}),
        );
        Ok(Self {
            enabled,
            key,
            reviewed,
            permission,
            profiles,
            domains,
            monthly,
            context,
        })
    }
    pub fn require(&self, input: &Value) -> Result<()> {
        if input["source"] != "public_search" {
            return Err(Failure("public_research_public_search_required"));
        }
        if !input["manual_people"]
            .as_array()
            .is_some_and(|a| a.is_empty())
            || !input["official_people"]
                .as_array()
                .is_some_and(|a| a.is_empty())
        {
            return Err(Failure("public_research_manual_import_required"));
        }
        if !self.enabled {
            return Err(Failure("public_research_disabled"));
        }
        if self.key.is_none() {
            return Err(Failure("public_research_local_key_required"));
        }
        if !self.reviewed || self.permission.is_none() {
            return Err(Failure("public_research_permission_required"));
        }
        if input["allow_paid"] != true {
            return Err(Failure("public_research_paid_opt_in_required"));
        }
        if input["research_mode"] == "public_profiles" && !self.profiles {
            return Err(Failure("public_research_profile_retention_not_authorized"));
        }
        if input["research_mode"] == "official_company"
            && !input["company_domain"]
                .as_str()
                .is_some_and(|s| self.domains.contains_key(s))
        {
            return Err(Failure("public_research_official_domain_not_authorized"));
        }
        if self.monthly < 1 {
            return Err(Failure("public_research_local_request_limit_exhausted"));
        }
        Ok(())
    }
    pub fn status(&self) -> Value {
        json!({"provider":"serper","enabled":self.enabled,"credentials_configured":self.key.is_some(),"retention_reviewed":self.reviewed && self.permission.is_some(),"profile_result_retention_authorized":self.profiles,"official_domains_configured":self.domains.len(),"monthly_local_request_limit":self.monthly,"budget_unit":"search_request","provider_balance_verified":false,"live_verified":false,"dispatch_authorized":false})
    }
}
