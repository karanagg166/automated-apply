//! Saved deployment prerequisites only; never a provider probe or dispatch grant.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub const APIFY_PORTALS: &[&str] = &[
    "naukri",
    "instahyre",
    "wellfound",
    "work_at_a_startup",
    "cutshort",
    "hirist",
    "foundit",
    "indeed",
    "glassdoor",
];
const PUBLIC: &[&str] = &[
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "remotive",
    "arbeitnow",
    "hacker_news",
];
pub struct Settings {
    boards: BTreeMap<String, Value>,
    actors: Map<String, Value>,
    routes: Map<String, Value>,
    apify_token_present: bool,
    monthly: f64,
    per_run: f64,
    search_enabled: bool,
    search_key_present: bool,
    search_rights_reviewed: bool,
    search_permission_present: bool,
}
fn invalid() -> Failure {
    Failure("invalid_discovery_source_settings")
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let object = |key: &str| -> Result<Map<String, Value>> {
            let Some(raw) = values.get(key) else {
                return Ok(Map::new());
            };
            if raw.len() > 524288 {
                return Err(invalid());
            }
            serde_json::from_str::<Value>(raw)
                .ok()
                .and_then(|v| v.as_object().filter(|v| v.len() <= 100).cloned())
                .ok_or_else(invalid)
        };
        let cost = |key: &str, max: f64| -> Result<f64> {
            values
                .get(key)
                .map(String::as_str)
                .unwrap_or("0")
                .parse::<f64>()
                .ok()
                .filter(|n| n.is_finite() && *n >= 0.0 && *n <= max)
                .ok_or_else(invalid)
        };
        let mut boards = BTreeMap::new();
        for source in &PUBLIC[..4] {
            let map = object(&format!("{}_BOARDS", source.to_ascii_uppercase()))?;
            let mut seen = BTreeSet::new();
            if (*source != "greenhouse" && map.len() > 10)
                || map.iter().any(|(id, company)| {
                    id.is_empty()
                        || id.len() > 100
                        || !id
                            .bytes()
                            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
                        || !seen.insert(id.to_ascii_lowercase())
                        || !company.as_str().is_some_and(|s| {
                            !s.trim().is_empty() && s.trim().chars().count() <= 255
                        })
                })
            {
                return Err(invalid());
            }
            boards.insert((*source).into(), Value::Object(map));
        }
        if values
            .get("LEVER_REGION")
            .is_some_and(|v| !matches!(v.as_str(), "global" | "eu"))
        {
            return Err(invalid());
        }
        let actors = object("APIFY_SOURCES")?;
        let routes = object("APIFY_SOURCE_ROUTES")?;
        if actors.values().any(|v| !v.is_object())
            || routes.values().any(|v| {
                !v.as_array()
                    .is_some_and(|a| a.len() <= 100 && a.iter().all(Value::is_object))
            })
        {
            return Err(invalid());
        }
        let present = |key: &str| values.get(key).is_some_and(|v| !v.trim().is_empty());
        let permission = values
            .get("PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL")
            .filter(|s| !s.trim().is_empty())
            .map(|s| crate::resources::public_https(s).ok_or_else(invalid))
            .transpose()?;
        Ok(Self {
            boards,
            actors,
            routes,
            apify_token_present: present("APIFY_API_TOKEN"),
            monthly: cost("APIFY_MONTHLY_LIMIT_USD", f64::MAX)?,
            per_run: cost("APIFY_PER_RUN_CAP_USD", 100.0)?,
            search_enabled: crate::configuration::boolean(values, "PEOPLE_SEARCH_ENABLED", false)?,
            search_key_present: present("SERPER_API_KEY"),
            search_rights_reviewed: crate::configuration::boolean(
                values,
                "PUBLIC_SEARCH_RIGHTS_REVIEWED",
                false,
            )?,
            search_permission_present: permission.is_some(),
        })
    }
    fn actor_ready(&self, source: &str, now: DateTime<Utc>) -> bool {
        let fallback = self.actors.get(source).cloned().unwrap_or(json!({}));
        let configs = self
            .routes
            .get(source)
            .and_then(Value::as_array)
            .filter(|a| !a.is_empty())
            .cloned()
            .unwrap_or(vec![fallback]);
        configs.len() <= 5
            && configs.into_iter().any(|v| {
                crate::apify_config::preflight(
                    v,
                    self.apify_token_present,
                    self.monthly,
                    self.per_run,
                    now,
                )
                .is_ok_and(|v| v["configuration_review_ready"] == true)
            })
    }
    pub fn jobs(&self, now: DateTime<Utc>) -> Value {
        let mut output = Vec::new();
        for source in PUBLIC {
            let board = self.boards.get(*source);
            let configured = board.is_none_or(|b| b.as_object().is_some_and(|b| !b.is_empty()));
            let config = if board.is_some() {
                json!({"boards_configured":configured,"board_allowlist_required":true})
            } else {
                json!({})
            };
            output.push(source_row(
                source,
                "direct_api",
                if configured {
                    "available"
                } else {
                    "configuration_required"
                },
                "free",
                true,
                config,
                false,
            ));
        }
        for source in APIFY_PORTALS {
            let configured = self.actor_ready(source, now);
            let mut row = source_row(
                source,
                "apify",
                if configured {
                    "available"
                } else {
                    "configuration_required"
                },
                "paid",
                configured,
                json!({"configured":configured,"actor_review_required":true}),
                false,
            );
            row["authentication"] =
                json!("Apify bearer token and reviewed, permitted actor configuration");
            if matches!(*source, "wellfound" | "work_at_a_startup") {
                row["operations"] = json!(["jobs", "company_intelligence"])
            }
            output.push(row);
        }
        for (source, reason) in [
            ("internshala", None),
            (
                "simplify",
                Some("No job-seeker collection authorization verified"),
            ),
            (
                "workday",
                Some("Tenant feed access requires separately verified permission"),
            ),
            (
                "company_careers",
                Some("Import an owner-reviewed URL and listing facts"),
            ),
        ] {
            let mut row = source_row(
                source,
                "manual",
                "manual_import_only",
                "free",
                true,
                reason
                    .map(|reason| json!({"collection_supported":false,"permission_basis":reason}))
                    .unwrap_or(json!({})),
                false,
            );
            row["operations"] = json!(["manual_import"]);
            output.push(row);
        }
        let mut manual = source_row(
            "manual",
            "manual",
            "available",
            "free",
            true,
            json!({}),
            false,
        );
        manual["operations"] = json!(["manual_import"]);
        output.push(manual);
        let mut linkedin = source_row(
            "linkedin",
            "restricted",
            "authorization_required",
            "free",
            false,
            json!({}),
            false,
        );
        linkedin["authentication"] =
            json!("Permitted search provider or user-supplied public URLs");
        linkedin["operations"] = json!(["manual_import", "profile_urls_via_public_search"]);
        output.push(linkedin);
        output.push(source_row(
            "apify",
            "restricted",
            "unsupported",
            "free",
            false,
            json!({}),
            false,
        ));
        let mut gmail = source_row(
            "gmail_alert",
            "gmail",
            "manual_import_only",
            "account_dependent",
            false,
            json!({}),
            false,
        );
        gmail["operations"] = json!(["manual_import"]);
        gmail["authentication"] = json!("OAuth read-only authorization");
        output.push(gmail);
        for (source, interval) in [("himalayas", 86400), ("we_work_remotely", 1800)] {
            let mut row = source_row(
                source,
                "direct_api",
                "available",
                "free",
                true,
                json!({}),
                true,
            );
            row["minimum_interval_seconds"] = json!(interval);
            output.push(row);
        }
        json!({"sources":output,"evidence_basis":"saved_configuration_not_current_provider_probe","provider_calls":0,"writes":0})
    }
    pub fn apify_settings(&self, now: DateTime<Utc>) -> Value {
        let sources = self.jobs(now)["sources"]
            .as_array()
            .expect("source list")
            .iter()
            .filter(|v| v["adapter_type"] == "apify")
            .cloned()
            .collect::<Vec<_>>();
        json!({"provider":"apify","transport":"official_api","local_token_configured":self.apify_token_present,
            "local_mcp_verified":false,"account_rotation":false,"budget_key":"apify",
            "monthly_limit_usd":self.monthly,"per_run_cap_usd":self.per_run,
            "linkedin_collection_enabled":false,"execution_authorized":false,
            "investigated_actors":crate::apify_metadata::INVESTIGATED_ACTORS,"sources":sources})
    }
    pub fn actor_metadata_allowed(&self, actor: &str) -> bool {
        crate::apify_metadata::INVESTIGATED_ACTORS.contains(&actor)
            || self
                .actors
                .values()
                .any(|v| v["actor_id"].as_str() == Some(actor))
            || self
                .routes
                .values()
                .filter_map(Value::as_array)
                .flatten()
                .any(|v| v["actor_id"].as_str() == Some(actor))
    }
    pub fn startups(&self, now: DateTime<Utc>) -> Value {
        let mut output = Vec::new();
        for source in [
            "hacker_news",
            "greenhouse",
            "remotive",
            "arbeitnow",
            "lever",
            "ashby",
            "smartrecruiters",
            "himalayas",
            "we_work_remotely",
        ] {
            let configured = self
                .boards
                .get(source)
                .is_none_or(|b| b.as_object().is_some_and(|b| !b.is_empty()));
            let interval = match source {
                "remotive" => 21600,
                "himalayas" => 86400,
                "we_work_remotely" => 1800,
                _ => 60,
            };
            output.push(json!({"provider":source,"modes":["job_led"],"availability":if configured{"available"}else{"configuration_required"},"pricing":"free","configured":configured,"authorized":true,"permission_basis":"documented_public_read_api","minimum_interval_seconds":interval,"native_execution_implemented":false,"live_verified":false,"dispatch_authorized":false}));
        }
        for source in ["wellfound", "work_at_a_startup"] {
            let configured = self.actor_ready(source, now);
            output.push(json!({"provider":source,"modes":["job_led"],"availability":if configured{"available"}else{"configuration_required"},"configured":configured,"authorized":configured,"pricing":"paid","permission_basis":"operator_reviewed_actor_required","native_execution_implemented":false,"live_verified":false,"dispatch_authorized":false}));
        }
        output.push(json!({"provider":"yc_directory","modes":[],"availability":"unsupported","configured":false,"authorized":false,"pricing":"unknown","permission_basis":"no_supported_directory_api_or_license_verified","manual_reference":"https://www.ycombinator.com/companies","native_execution_implemented":false,"live_verified":false,"dispatch_authorized":false}));
        output.push(json!({"provider":"manual","modes":["company_first"],"availability":"manual_import_only","configured":true,"authorized":false,"pricing":"free","permission_basis":"per_import_rights_confirmation_and_evidence_required","native_execution_implemented":true,"live_verified":false,"dispatch_authorized":false}));
        let configured = self.search_enabled && self.search_key_present;
        let authorized = self.search_rights_reviewed && self.search_permission_present;
        output.push(json!({"provider":"public_search","modes":["professional_research"],"availability":if configured && authorized{"available"}else{"configuration_required"},"configured":configured,"authorized":authorized,"pricing":"paid","permission_basis":"third_party_retention_rights_required","native_execution_implemented":true,"live_verified":false,"dispatch_authorized":false}));
        json!({"sources":output,"evidence_basis":"saved_configuration_not_current_provider_probe","provider_calls":0,"writes":0})
    }
    pub fn startup(&self, source: &str, now: DateTime<Utc>) -> Result<Value> {
        self.startups(now)["sources"]
            .as_array()
            .and_then(|a| a.iter().find(|r| r["provider"] == source))
            .cloned()
            .ok_or(Failure("startup_source_unknown"))
    }
}
fn source_row(
    id: &str,
    adapter: &str,
    availability: &str,
    pricing: &str,
    enabled: bool,
    configuration: Value,
    implemented: bool,
) -> Value {
    let display = match id {
        "smartrecruiters" => "SmartRecruiters".into(),
        "work_at_a_startup" => "YC Work at a Startup".into(),
        "hacker_news" => "Hacker News Hiring".into(),
        "gmail_alert" => "Gmail alerts (legacy parser)".into(),
        "company_careers" => "Company career page".into(),
        "manual" => "Manual import".into(),
        "linkedin" => "LinkedIn".into(),
        "apify" => "Apify (select a platform)".into(),
        "we_work_remotely" => "We Work Remotely".into(),
        _ => {
            let mut chars = id.chars();
            format!(
                "{}{}",
                chars
                    .next()
                    .map(|c| c.to_ascii_uppercase())
                    .unwrap_or_default(),
                chars.as_str()
            )
        }
    };
    json!({"id":id,"display_name":display,"adapter_type":adapter,"operations":["jobs"],"authentication":"none","availability":availability,"pricing":pricing,"enabled":enabled,"read_only":true,"mutation_capabilities":[],"configuration":configuration,"live_verified":false,"native_execution_implemented":implemented,"dispatch_authorized":false})
}
