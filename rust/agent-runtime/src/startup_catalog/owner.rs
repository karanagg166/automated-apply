//! Owner startup discovery boundary. Preview is read-only; manual runs keep original claims.
use crate::{
    Failure, Result,
    research_contract::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Route {
    Sources,
    JobSources,
    Preview,
    Runs,
    Run(Uuid),
    Complete(Uuid),
}
impl Route {
    pub fn method(self) -> &'static str {
        match self {
            Self::Preview | Self::Runs | Self::Complete(_) => "POST",
            _ => "GET",
        }
    }
    pub fn accepts(self, method: &str) -> bool {
        if matches!(self, Self::Run(_)) {
            matches!(method, "GET" | "PUT")
        } else {
            method == self.method()
        }
    }
    pub fn allow(self) -> &'static str {
        if matches!(self, Self::Run(_)) {
            "GET, PUT"
        } else {
            self.method()
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/startups/sources" => Some(Route::Sources),
        "/api/v1/discovery/sources" => Some(Route::JobSources),
        "/api/v1/startups/discovery/preview" => Some(Route::Preview),
        "/api/v1/startups/discovery/runs" => Some(Route::Runs),
        _ => {
            let tail = path.strip_prefix("/api/v1/startups/discovery/runs/")?;
            let (raw, complete) = tail
                .strip_suffix("/complete")
                .map(|id| (id, true))
                .unwrap_or((tail, false));
            let id: Uuid = raw.parse().ok()?;
            if id.is_nil() {
                return None;
            }
            Some(if complete {
                Route::Complete(id)
            } else {
                Route::Run(id)
            })
        }
    }
}
pub async fn preview(
    c: &mut PgConnection,
    input: Value,
    settings: &crate::source_registry::Settings,
) -> Result<Value> {
    let mut tx = c
        .begin()
        .await
        .map_err(|_| Failure("startup_catalog_database_error"))?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(|_| Failure("startup_catalog_database_error"))?;
    let now: i64 =
        sqlx::query_scalar("SELECT floor(extract(epoch FROM current_timestamp))::bigint")
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| Failure("startup_catalog_database_error"))?;
    let now =
        DateTime::<Utc>::from_timestamp(now, 0).ok_or(Failure("invalid_startup_catalog_record"))?;
    let input = research_contract::normalize(Kind::StartupKeyed, input, now)?;
    let source = settings.startup(
        input["source"]
            .as_str()
            .ok_or(Failure("invalid_startup_contract"))?,
        now,
    )?;
    let profile =
        super::detail::profile_in(&mut tx, input["filters"]["use_profile"] == true).await?;
    let effective = |key: &str, profile_key: &str| -> Value {
        input["filters"][key]
            .as_array()
            .filter(|a| !a.is_empty())
            .map(|a| json!(a))
            .unwrap_or_else(|| {
                profile
                    .as_ref()
                    .map(|p| p["preferences"][profile_key].clone())
                    .unwrap_or(json!([]))
            })
    };
    let mut result = json!({"source":source,"mode":input["mode"],"filters":input["filters"],"profile_version":profile.as_ref().map(|p|p["version"].clone()),"effective_roles":effective("roles","target_titles"),"effective_locations":effective("locations","preferred_locations"),"provider_calls":0,"writes":0,"company_first_available":source["modes"].as_array().is_some_and(|a|a.contains(&input["mode"])),"message":"Company-first collection requires a permission-confirmed import; no directory crawl is available","live_verified":false,"dispatch_authorized":false});
    if input["mode"] == "job_led" {
        let query = crate::job_sources::scope::effective_query(&input["query"], profile.as_ref())?;
        result["query"] = query.clone();
        result["job_led_available"] = json!(
            source["native_execution_implemented"] == true
                && source["configured"] == true
                && source["authorized"] == true
        );
        result["message"] = json!(
            "Planning only; no provider calls, budget reservation or saved records. Company filters apply to retained job-to-company evidence; unknown company facts remain unknown."
        );
        if source["pricing"] == "paid" {
            let paid = settings.paid_preview(
                input["source"]
                    .as_str()
                    .ok_or(Failure("invalid_startup_contract"))?,
                query,
                input["allow_paid"] == true,
                now,
            );
            result["job_led_available"] =
                json!(result["job_led_available"] == true && paid["ready"] == true);
            result["paid_execution"] = paid;
        }
    }
    tx.commit()
        .await
        .map_err(|_| Failure("startup_catalog_database_error"))?;
    Ok(result)
}
