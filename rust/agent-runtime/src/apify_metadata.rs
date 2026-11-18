//! Observed public actor/account metadata. This module cannot execute an actor or read datasets.
pub mod owner;
pub mod transport;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

pub const INVESTIGATED_ACTORS: [&str; 3] = [
    "harvestapi/linkedin-company-search",
    "harvestapi/linkedin-company",
    "harvestapi/linkedin-company-employees",
];
fn bounded(value: &Value) -> Result<()> {
    if value.to_string().len() > 1048576 {
        return Err(Failure("apify_metadata_response_limit"));
    }
    Ok(())
}
pub fn inspect_request(value: &Value) -> Result<&str> {
    let fields = value
        .as_object()
        .filter(|o| o.len() == 1)
        .ok_or(Failure("apify_actor_inspect_invalid"))?;
    let actor = fields
        .get("actor_id")
        .and_then(Value::as_str)
        .ok_or(Failure("apify_actor_inspect_invalid"))?;
    let actor = actor.trim();
    crate::apify_config::safe_actor(actor)?;
    Ok(actor)
}
/// Unique inline schema or one local component. No URL resolution, recursive expansion or evaluation.
pub fn input_schema(document: &Value) -> Result<Option<Value>> {
    bounded(document)?;
    let Some(paths) = document.get("paths").and_then(Value::as_object) else {
        return Ok(None);
    };
    let mut candidates = Vec::new();
    for path in paths.values() {
        let schema = path.pointer("/post/requestBody/content/application~1json/schema");
        if let Some(schema) = schema.filter(|s| s.is_object())
            && !candidates.contains(&schema)
        {
            candidates.push(schema);
        }
    }
    if candidates.len() != 1 {
        return Ok(None);
    }
    let mut schema = candidates[0];
    if let Some(reference) = schema.get("$ref") {
        let Some(name) = reference
            .as_str()
            .and_then(|s| s.strip_prefix("#/components/schemas/"))
        else {
            return Ok(None);
        };
        // Preserve actual legacy single-component lookup, never interpret arbitrary JSON pointers.
        let name = name.rsplit('/').next().unwrap_or("");
        let Some(found) = document
            .get("components")
            .and_then(|c| c.get("schemas"))
            .and_then(|c| c.get(name))
        else {
            return Ok(None);
        };
        schema = found;
    }
    if !schema.is_object() {
        return Ok(None);
    }
    if schema.to_string().len() > 65536 {
        return Err(Failure("apify_actor_schema_limit"));
    }
    Ok(Some(schema.clone()))
}
pub fn actor(
    actor_id: &str,
    payload: &Value,
    document: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let safe = crate::apify_config::safe_actor(actor_id)?;
    bounded(payload)?;
    let data = payload
        .get("data")
        .and_then(Value::as_object)
        .ok_or(Failure("apify_actor_metadata_invalid"))?;
    let title = match data.get("title") {
        None | Some(Value::Null) => Value::Null,
        Some(Value::String(title)) if title.chars().count() <= 1000 => json!(title),
        _ => return Err(Failure("apify_actor_metadata_invalid")),
    };
    let empty = json!([]);
    let pricing = data.get("pricingInfos").unwrap_or(&empty);
    if !pricing
        .as_array()
        .is_some_and(|a| a.len() <= 100 && a.iter().all(Value::is_object))
        || pricing.to_string().len() > 131072
    {
        return Err(Failure("apify_pricing_metadata_invalid"));
    }
    let schema = input_schema(document)?;
    let digest = schema
        .as_ref()
        .filter(|v| v.as_object().is_some_and(|m| !m.is_empty()))
        .map(|v| {
            format!(
                "{:x}",
                Sha256::digest(crate::python_json::serialize(v, false, true).as_bytes())
            )
        });
    Ok(
        json!({"actor_id":actor_id,"title":title,"observed_at":now.to_rfc3339(),"pricing":pricing,
        "input_schema":schema,"schema_digest":digest,"collection_status":"disabled_pending_review",
        "source_url":format!("https://api.apify.com/v2/actors/{safe}")}),
    )
}
pub fn store(payload: &Value, limit: usize) -> Result<Vec<Value>> {
    if !(1..=20).contains(&limit) {
        return Err(Failure("apify_store_query_invalid"));
    }
    bounded(payload)?;
    let items = payload
        .pointer("/data/items")
        .and_then(Value::as_array)
        .filter(|a| a.len() <= 1000)
        .ok_or(Failure("apify_store_schema_invalid"))?;
    let mut out = Vec::new();
    for item in items.iter().take(limit).filter(|i| i.is_object()) {
        let mut selected = Map::new();
        for key in ["id", "name", "username", "title"] {
            let value = item.get(key).unwrap_or(&Value::Null);
            if !value.is_null() && !value.as_str().is_some_and(|s| s.chars().count() <= 1000) {
                return Err(Failure("apify_store_schema_invalid"));
            }
            selected.insert(key.into(), value.clone());
        }
        let pricing = item.get("pricingInfos").unwrap_or(&Value::Null);
        if !pricing.is_null()
            && (!pricing
                .as_array()
                .is_some_and(|a| a.len() <= 100 && a.iter().all(Value::is_object))
                || pricing.to_string().len() > 131072)
        {
            return Err(Failure("apify_pricing_metadata_invalid"));
        }
        selected.insert("pricingInfos".into(), pricing.clone());
        out.push(Value::Object(selected));
    }
    Ok(out)
}
const LIMIT_FIELDS: &[&str] = &[
    "maxMonthlyUsageUsd",
    "maxMonthlyActorComputeUnits",
    "maxMonthlyExternalDataTransferGbytes",
    "maxMonthlyProxySerps",
    "maxMonthlyResidentialProxyGbytes",
    "maxActorMemoryGbytes",
    "maxActorCount",
    "maxActorTaskCount",
    "maxConcurrentActorJobs",
    "maxTeamAccountSeatCount",
    "dataRetentionDays",
    "maxScheduleCount",
    "maxMonthlyUnblockerUnits",
];
const CURRENT_FIELDS: &[&str] = &[
    "monthlyUsageUsd",
    "monthlyActorComputeUnits",
    "monthlyExternalDataTransferGbytes",
    "monthlyProxySerps",
    "monthlyResidentialProxyGbytes",
    "actorMemoryGbytes",
    "actorCount",
    "actorTaskCount",
    "activeActorJobCount",
    "teamAccountSeatCount",
    "scheduleCount",
    "monthlyUnblockerUnits",
];
fn numeric(value: &Value, fields: &[&str]) -> Result<Value> {
    let object = value
        .as_object()
        .ok_or(Failure("apify_account_metadata_invalid"))?;
    let mut out = Map::new();
    for field in fields {
        if let Some(value) = object.get(*field) {
            if !value.as_f64().is_some_and(|n| n.is_finite() && n >= 0.0) {
                return Err(Failure("apify_account_metadata_invalid"));
            }
            out.insert((*field).into(), value.clone());
        }
    }
    Ok(Value::Object(out))
}
fn cycle(value: &Value) -> Result<Value> {
    let parse = |key| -> Result<DateTime<Utc>> {
        value
            .get(key)
            .and_then(Value::as_str)
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .map(|v| v.to_utc())
            .ok_or(Failure("apify_account_metadata_invalid"))
    };
    let start = parse("startAt")?;
    let end = parse("endAt")?;
    if end <= start {
        return Err(Failure("apify_account_metadata_invalid"));
    }
    Ok(json!({"startAt":start.to_rfc3339(),"endAt":end.to_rfc3339()}))
}
/// Closed account projection: never echo provider account IDs, email, arbitrary blobs or diagnostic text.
pub fn account(limits: &Value, usage: &Value, now: DateTime<Utc>) -> Result<Value> {
    bounded(limits)?;
    bounded(usage)?;
    let l = limits
        .get("data")
        .filter(|v| v.is_object())
        .ok_or(Failure("apify_account_metadata_invalid"))?;
    let u = usage
        .get("data")
        .filter(|v| v.is_object())
        .ok_or(Failure("apify_account_metadata_invalid"))?;
    let lc = cycle(&l["monthlyUsageCycle"])?;
    let uc = cycle(&u["usageCycle"])?;
    if lc != uc {
        return Err(Failure("apify_account_cycle_changed"));
    }
    let limits = numeric(&l["limits"], LIMIT_FIELDS)?;
    let current = numeric(&l["current"], CURRENT_FIELDS)?;
    if limits.get("maxMonthlyUsageUsd").is_none() || current.get("monthlyUsageUsd").is_none() {
        return Err(Failure("apify_account_metadata_invalid"));
    }
    let totals = numeric(
        u,
        &[
            "totalUsageCreditsUsdBeforeVolumeDiscount",
            "totalUsageCreditsUsdAfterVolumeDiscount",
        ],
    )?;
    if totals.as_object().is_none_or(|o| o.len() != 2) {
        return Err(Failure("apify_account_metadata_invalid"));
    }
    let mut usage = totals.as_object().expect("numeric object").clone();
    usage.insert("usageCycle".into(), uc);
    Ok(
        json!({"provider":"apify","transport":"official_api","authenticated":true,
        "limits":{"monthlyUsageCycle":lc,"limits":limits,"current":current},"usage":usage,
        "observed_at":now.to_rfc3339(),"execution_authorized":false}),
    )
}
