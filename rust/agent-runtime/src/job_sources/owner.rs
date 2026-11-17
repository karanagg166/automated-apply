//! Owner boundary: read-only preview/history and stable original public run identities.
use crate::{Failure, Result, source_registry::Settings};
use chrono::Utc;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Route {
    Preview,
    Runs,
    Run(Uuid),
    Complete(Uuid),
    Read(Uuid, Uuid),
    CompleteRead(Uuid, Uuid),
}
impl Route {
    pub fn accepts(self, method: &str) -> bool {
        match self {
            Self::Preview | Self::Runs | Self::Complete(_) | Self::CompleteRead(_, _) => {
                method == "POST"
            }
            Self::Run(_) | Self::Read(_, _) => matches!(method, "GET" | "PUT"),
        }
    }
    pub fn allow(self) -> &'static str {
        match self {
            Self::Preview | Self::Runs | Self::Complete(_) | Self::CompleteRead(_, _) => "POST",
            Self::Run(_) | Self::Read(_, _) => "GET, PUT",
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/discovery/preview" => Some(Route::Preview),
        "/api/v1/discovery/runs" => Some(Route::Runs),
        _ => {
            let tail = path.strip_prefix("/api/v1/discovery/runs/")?;
            if let Some((parent, tail)) = tail.split_once("/reads/") {
                let parent: Uuid = parent.parse().ok()?;
                let (read, complete) = tail
                    .strip_suffix("/complete")
                    .map(|id| (id, true))
                    .unwrap_or((tail, false));
                let read: Uuid = read.parse().ok()?;
                if parent.is_nil() || read.is_nil() || parent == read {
                    return None;
                }
                return Some(if complete {
                    Route::CompleteRead(parent, read)
                } else {
                    Route::Read(parent, read)
                });
            }
            if let Some(id) = tail.strip_suffix("/complete") {
                id.parse().ok().map(Route::Complete)
            } else {
                tail.parse().ok().map(Route::Run)
            }
        }
    }
}
pub fn request(raw: Value) -> Result<Value> {
    super::scope::normalize(raw)
}
pub fn execution_request(raw: Value) -> Result<Value> {
    let value = request(raw)?;
    let source = value["source"]
        .as_str()
        .ok_or(Failure("invalid_discovery_run_request"))?;
    if crate::source_registry::APIFY_PORTALS.contains(&source) {
        if value["manual_jobs"]
            .as_array()
            .is_none_or(|a| !a.is_empty())
        {
            return Err(Failure("apify_manual_records_not_supported"));
        }
        return Ok(value);
    }
    if super::plan::Source::parse(source).is_err() {
        return Err(Failure("discovery_source_execution_not_implemented"));
    }
    if value["manual_jobs"]
        .as_array()
        .is_none_or(|a| !a.is_empty())
    {
        return Err(Failure("public_job_manual_source_required"));
    }
    Ok(value)
}
pub fn compatibility_id(request: &Value) -> Result<Uuid> {
    let key = request["idempotency_key"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(Failure("discovery_run_idempotency_key_required"))?;
    Ok(Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!(
            "automated-apply:{}-discovery:{key}",
            if crate::source_registry::APIFY_PORTALS
                .contains(&request["source"].as_str().unwrap_or(""))
            {
                "apify"
            } else {
                "public"
            }
        )
        .as_bytes(),
    ))
}
pub async fn preview(c: &mut PgConnection, settings: &Settings, raw: Value) -> Result<Value> {
    let input = request(raw)?;
    let source = settings.job(
        input["source"]
            .as_str()
            .ok_or(Failure("invalid_discovery_run_request"))?,
        Utc::now(),
    )?;
    let mut tx = c
        .begin()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    let profile =
        crate::startup_catalog::detail::profile_in(&mut tx, input["use_profile"] == true).await?;
    let query = super::scope::effective_query(&input["query"], profile.as_ref())?;
    let out = json!({"source":source,"query":query,"explicit_query":input["query"],"profile_version":profile.as_ref().map(|p|p["version"].clone()),"jobs":[],"provider_calls":0,"writes":0,"estimated_usd":if source["pricing"]=="free"{json!(0)}else{Value::Null},"estimate_only":true,"message":"Planning only; no providers called and no jobs or runs written","dispatch_authorized":false,"live_verified":false});
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    Ok(out)
}
/// Saved legacy history remains visible without adopting missing original native authority.
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    match native_kind(c, id).await? {
        NativeKind::Paid => return crate::apify_jobs::runs::read(c, id).await,
        NativeKind::Public => return super::runs::read(c, id).await,
        NativeKind::Legacy => {}
    }
    match super::runs::read(c, id).await {
        Err(e) if e.0 == "discovery_run_original_scope_missing" => legacy(c, id).await,
        result => result,
    }
}
async fn legacy(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c
        .begin()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    let row:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1").bind(id).fetch_optional(&mut *tx).await.map_err(|_|Failure("discovery_run_database_error"))?;
    let row = row
        .ok_or(Failure("discovery_run_not_found"))?
        .ok_or(Failure("discovery_run_saved_limit"))?;
    // The second snapshot may observe a concurrent native admission; it must use native validation.
    let native: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=ANY($1))")
            .bind(vec![
                format!("job_run:{}", id.simple()),
                format!("apify_owner:{}", id.simple()),
            ])
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| Failure("discovery_run_database_error"))?;
    if native {
        return Err(Failure("discovery_run_read_snapshot_changed"));
    }
    let source = row["source"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 100)
        .ok_or(Failure("invalid_discovery_owner_run"))?;
    let recorded = row["status"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 50)
        .ok_or(Failure("invalid_discovery_owner_run"))?;
    super::access::time(&row["started_at"])?;
    if !row["finished_at"].is_null() {
        super::access::time(&row["finished_at"])?;
    }
    let mut counts = json!({});
    for key in [
        "discovered",
        "inserted",
        "updated",
        "duplicate",
        "rejected",
        "failed",
        "skipped",
    ] {
        if let Some(value) = row["counts"].get(key) {
            if value.as_u64().is_none_or(|n| n > 10000000) {
                return Err(Failure("invalid_discovery_owner_run"));
            }
            counts[key] = value.clone();
        }
    }
    let ids = match row["query_summary"].get("job_ids") {
        None | Some(Value::Null) => vec![],
        Some(Value::Array(a)) if a.len() <= 100 => a
            .iter()
            .map(|v| {
                v.as_str()
                    .and_then(|s| s.parse::<Uuid>().ok())
                    .filter(|id| !id.is_nil())
                    .map(|id| json!(id))
                    .ok_or(Failure("invalid_discovery_owner_run"))
            })
            .collect::<Result<Vec<_>>>()?,
        _ => return Err(Failure("invalid_discovery_owner_run")),
    };
    let out = json!({"id":id,"source":source,"status":if recorded=="running"{"recovery_required"}else{recorded},"counts":counts,"errors":["Legacy saved run; original native scope and execution evidence are unavailable"],"started_at":row["started_at"],"finished_at":row["finished_at"],"provider_run_id":null,"usage":{"stage":"legacy_read_only","recorded_status":recorded,"replay_authorized":false},"rankings":[],"job_ids":ids,"original_scope_available":false,"local_intake_complete":null,"rankings_complete":null,"application_dispatch":false,"live_verified":false,"evidence_basis":"legacy_saved_row_only"});
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    Ok(out)
}

pub(crate) enum NativeKind {
    Public,
    Paid,
    Legacy,
}
/// Original private keys select a native implementation; a legacy row never grants adoption.
pub(crate) async fn native_kind(c: &mut PgConnection, id: Uuid) -> Result<NativeKind> {
    let mut tx = c
        .begin()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    let kinds: Vec<String> =
        sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key=ANY($1) ORDER BY key")
            .bind(vec![
                format!("job_run:{}", id.simple()),
                format!("apify_owner:{}", id.simple()),
            ])
            .fetch_all(&mut *tx)
            .await
            .map_err(|_| Failure("discovery_run_database_error"))?;
    let kind = match kinds.as_slice() {
        [] => NativeKind::Legacy,
        [key] if key.starts_with("job_run:") => NativeKind::Public,
        [_] => NativeKind::Paid,
        _ => return Err(Failure("discovery_run_original_scope_ambiguous")),
    };
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_database_error"))?;
    Ok(kind)
}
