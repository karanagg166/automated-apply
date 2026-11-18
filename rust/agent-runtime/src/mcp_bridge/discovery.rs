//! Closed MCP mappings into the existing owner boundary. No provider client or grants here.
use super::{decode, definition};
use crate::{Failure, Result};
use chrono::Utc;
use reqwest::Method;
use rmcp::model::{Tool, ToolAnnotations};
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

pub(super) fn metadata(name: &str) -> bool {
    matches!(name, "apify_inspect_account" | "apify_inspect_actor")
}
pub(super) fn long_running(name: &str) -> bool {
    matches!(
        name,
        "discovery_run"
            | "apify_read_recover"
            | "startup_discovery_run"
            | "discovery_complete"
            | "apify_read_complete"
            | "startup_discovery_complete"
    )
}
pub(super) fn mutating(name: &str) -> bool {
    long_running(name) || metadata(name)
}
pub(super) fn authorize(name: &str, discovery: bool, inspect: bool) -> Result<()> {
    if long_running(name) && !discovery || metadata(name) && !inspect {
        return Err(Failure("mcp_capability_not_enabled"));
    }
    Ok(())
}
fn object(properties: Value, required: &[&str]) -> Value {
    json!({"type":"object","properties":properties,"required":required,"additionalProperties":false})
}
fn uuid() -> Value {
    json!({"type":"string","format":"uuid","description":"Original caller-retained nonnil UUID. Keep it after response loss; never replace an unknown attempt."})
}
fn consent() -> Value {
    json!({"type":"boolean","const":true,"description":"Explicit consent for this original attempt. Paid execution additionally requires request.allow_paid and current saved build/budget review."})
}
fn request_schema(startup: bool) -> Value {
    let mut schema: Value = serde_json::from_str(if startup {
        include_str!("../../schemas/startup-run-request.json")
    } else {
        include_str!("../../schemas/discovery-run-request.json")
    })
    .expect("frozen request schema");
    // Embed nested references with an absolute local JSON pointer into the wrapper schema.
    fn references(value: &mut Value) {
        match value {
            Value::Object(map) => {
                if let Some(Value::String(reference)) = map.get_mut("$ref")
                    && let Some(tail) = reference.strip_prefix("#/$defs/")
                {
                    *reference = format!("#/properties/request/$defs/{tail}");
                }
                for item in map.values_mut() {
                    references(item);
                }
            }
            Value::Array(items) => {
                for item in items {
                    references(item);
                }
            }
            _ => {}
        }
    }
    let properties = schema["properties"]
        .as_object_mut()
        .expect("request properties");
    properties.remove("idempotency_key");
    if startup {
        properties.remove("companies");
        properties.remove("permission_confirmed");
        properties.insert(
            "mode".into(),
            json!({"type":"string","const":"job_led","default":"job_led"}),
        );
        schema["required"]
            .as_array_mut()
            .expect("startup required fields")
            .retain(|field| field != "idempotency_key");
    } else {
        properties.remove("manual_jobs");
    }
    references(&mut schema);
    schema
}
pub(super) fn catalog(dispatch: bool, inspect: bool) -> Vec<Tool> {
    let empty = object(json!({}), &[]);
    let run = object(json!({"run_id":uuid()}), &["run_id"]);
    let read = object(
        json!({"run_id":uuid(),"read_request_id":uuid()}),
        &["run_id", "read_request_id"],
    );
    let mut tools = vec![];
    for (name, description) in [
        (
            "discovery_sources",
            "Read native source readiness, paid-plan blockers and configuration; no provider calls.",
        ),
        (
            "startup_sources",
            "Read job-led startup source capabilities. Source claims are not verified company facts.",
        ),
        (
            "apify_status",
            "Read saved Apify metadata freshness and held local reservations. No inspection, Actor start or provider credit claim.",
        ),
    ] {
        tools.push(definition(name, description, empty.clone(), true));
    }
    for (name, description, schema) in [
        (
            "discovery_run_status",
            "GET a retained original job discovery UUID, without dispatch or refresh.",
            run.clone(),
        ),
        (
            "startup_discovery_status",
            "GET a retained startup UUID and original child reference; no provider calls.",
            run.clone(),
        ),
        (
            "apify_read_status",
            "GET a retained bounded read UUID for its original parent; never creates or renews authority.",
            read.clone(),
        ),
    ] {
        tools.push(definition(name, description, schema, true));
    }
    for (name, startup, description) in [
        (
            "discovery_preview",
            false,
            "Plan the actual saved-profile job query and paid cap; no provider calls, writes or reservation.",
        ),
        (
            "startup_discovery_preview",
            true,
            "Plan job-led startup query/company filters without writes or paid execution.",
        ),
    ] {
        tools.push(definition(
            name,
            description,
            object(json!({"request":request_schema(startup)}), &["request"]),
            true,
        ));
    }
    if dispatch {
        for (name, startup, description) in [
            (
                "discovery_run",
                false,
                "Explicitly PUT one original discovery UUID using saved provider limits and consent. Persist UUID before calling. After unknown response use status; do not replace it or infer refunds. Never applies.",
            ),
            (
                "startup_discovery_run",
                true,
                "Explicitly PUT one original job-led startup UUID and deterministic job child. Keep UUID after response loss. Paid opt-in/build/budget and company provenance remain enforced. Never applies.",
            ),
        ] {
            tools.push(action(
                name,
                description,
                object(
                    json!({"run_id":uuid(),"consent":consent(),"request":request_schema(startup)}),
                    &["run_id", "consent", "request"],
                ),
                true,
                true,
            ));
        }
        tools.push(action("apify_read_recover","Explicitly PUT a distinct read UUID for an acknowledged original Apify run. Bounded GETs only; no Actor start/abort/refund. Keep both UUIDs after uncertainty. Existing lifetime/spacing/context controls remain.",object(json!({"run_id":uuid(),"read_request_id":uuid(),"consent":consent()}), &["run_id","read_request_id","consent"]),true,true));
        for (name, description, schema) in [
            (
                "discovery_complete",
                "Combine original retained job findings locally. No provider call or renewed grant; current original context required.",
                run.clone(),
            ),
            (
                "startup_discovery_complete",
                "Complete saved startup/child findings locally. Unknown provider state stays pending; no recovery dispatch.",
                run.clone(),
            ),
            (
                "apify_read_complete",
                "Combine complete saved read pages locally. No provider GET, Actor start/abort, refund or refreshed timestamps.",
                read.clone(),
            ),
        ] {
            tools.push(action(name, description, schema, false, true));
        }
    }
    if inspect {
        tools.push(action("apify_inspect_account","Explicit bounded official account metadata inspection with durable pacing/cache. No Actor execution, purchase or credit entitlement inference.",object(json!({"consent":consent()}), &["consent"]),true,false));
        tools.push(action("apify_inspect_actor","Explicit metadata inspection of an operator-allowlisted Actor identifier. No arbitrary URL, Actor execution or budget grant.",object(json!({"actor_id":{"type":"string","minLength":1,"maxLength":200},"consent":consent()}), &["actor_id","consent"]),true,false));
    }
    tools
}
fn action(
    name: &'static str,
    description: &'static str,
    schema: Value,
    external: bool,
    idempotent: bool,
) -> Tool {
    let mut tool = definition(name, description, schema, false);
    tool.annotations = Some(
        ToolAnnotations::new()
            .read_only(false)
            .destructive(false)
            .idempotent(idempotent)
            .open_world(external),
    );
    tool
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Attempt {
    run_id: Uuid,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadAttempt {
    run_id: Uuid,
    read_request_id: Uuid,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Start {
    run_id: Uuid,
    consent: bool,
    request: Value,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Recover {
    run_id: Uuid,
    read_request_id: Uuid,
    consent: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Preview {
    request: Value,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inspect {
    consent: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Actor {
    actor_id: String,
    consent: bool,
}
fn valid_id(id: Uuid) -> Result<Uuid> {
    if id.is_nil() {
        Err(Failure("invalid_tool_arguments"))
    } else {
        Ok(id)
    }
}
fn valid_read(parent: Uuid, read: Uuid) -> Result<()> {
    valid_id(parent)?;
    valid_id(read)?;
    if parent == read {
        return Err(Failure("invalid_tool_arguments"));
    }
    Ok(())
}
fn approved(value: bool) -> Result<()> {
    if value {
        Ok(())
    } else {
        Err(Failure("mcp_explicit_consent_required"))
    }
}
fn input(mut value: Value, startup: bool, execute: bool) -> Result<Value> {
    let fields = value
        .as_object_mut()
        .ok_or(Failure("invalid_tool_arguments"))?;
    // The UUID route is the sole identity. Manual imports are a separate owner flow.
    if [
        "idempotency_key",
        "manual_jobs",
        "companies",
        "permission_confirmed",
    ]
    .iter()
    .any(|key| fields.contains_key(*key))
    {
        return Err(Failure("invalid_tool_arguments"));
    }
    // MCP accepts real booleans; legacy HTTP coercion is not an extra tool grant.
    for key in ["allow_paid", "use_profile"] {
        if fields.get(key).is_some_and(|v| !v.is_boolean()) {
            return Err(Failure("invalid_tool_arguments"));
        }
    }
    if startup {
        fields.entry("mode").or_insert(json!("job_led"));
        if fields["mode"] != "job_led" {
            return Err(Failure("invalid_tool_arguments"));
        }
        crate::research_contract::normalize(
            crate::research_contract::Kind::StartupKeyed,
            value,
            Utc::now(),
        )
    } else if execute {
        if value["source"]
            .as_str()
            .is_some_and(crate::job_sources::manual::supports)
        {
            return Err(Failure("invalid_tool_arguments"));
        }
        crate::job_sources::owner::execution_request(value)
    } else {
        crate::job_sources::owner::request(value)
    }
}
type Operation = (Method, String, Option<Value>);
pub(super) fn operation(name: &str, args: Value) -> Option<Result<Operation>> {
    Some(match name {
        "discovery_sources" | "startup_sources" | "apify_status" => (|| {
            let _: super::Empty = decode(args)?;
            Ok((
                Method::GET,
                match name {
                    "discovery_sources" => "/api/v1/discovery/sources",
                    "startup_sources" => "/api/v1/startups/sources",
                    _ => "/api/v1/integrations/providers/apify",
                }
                .into(),
                None,
            ))
        })(),
        "discovery_preview" | "startup_discovery_preview" => (|| {
            let p: Preview = decode(args)?;
            let startup = name == "startup_discovery_preview";
            Ok((
                Method::POST,
                if startup {
                    "/api/v1/startups/discovery/preview"
                } else {
                    "/api/v1/discovery/preview"
                }
                .into(),
                Some(input(p.request, startup, false)?),
            ))
        })(),
        "discovery_run" | "startup_discovery_run" => (|| {
            let p: Start = decode(args)?;
            valid_id(p.run_id)?;
            approved(p.consent)?;
            let startup = name == "startup_discovery_run";
            Ok((
                Method::PUT,
                run_path(p.run_id, startup),
                Some(input(p.request, startup, true)?),
            ))
        })(),
        "discovery_run_status"
        | "startup_discovery_status"
        | "discovery_complete"
        | "startup_discovery_complete" => (|| {
            let p: Attempt = decode(args)?;
            valid_id(p.run_id)?;
            let complete = name.ends_with("_complete");
            let mut path = run_path(p.run_id, name.starts_with("startup_"));
            if complete {
                path.push_str("/complete");
            }
            Ok((
                if complete { Method::POST } else { Method::GET },
                path,
                complete.then(|| json!({})),
            ))
        })(),
        "apify_read_status" | "apify_read_complete" => (|| {
            let p: ReadAttempt = decode(args)?;
            valid_read(p.run_id, p.read_request_id)?;
            let complete = name.ends_with("_complete");
            let mut path = read_path(p.run_id, p.read_request_id);
            if complete {
                path.push_str("/complete");
            }
            Ok((
                if complete { Method::POST } else { Method::GET },
                path,
                complete.then(|| json!({})),
            ))
        })(),
        "apify_read_recover" => (|| {
            let p: Recover = decode(args)?;
            valid_read(p.run_id, p.read_request_id)?;
            approved(p.consent)?;
            Ok((
                Method::PUT,
                read_path(p.run_id, p.read_request_id),
                Some(json!({})),
            ))
        })(),
        "apify_inspect_account" => (|| {
            let p: Inspect = decode(args)?;
            approved(p.consent)?;
            Ok((
                Method::POST,
                "/api/v1/integrations/providers/apify/inspect".into(),
                None,
            ))
        })(),
        "apify_inspect_actor" => (|| {
            let p: Actor = decode(args)?;
            approved(p.consent)?;
            crate::apify_config::safe_actor(&p.actor_id)?;
            Ok((
                Method::POST,
                "/api/v1/integrations/providers/apify/actors/inspect".into(),
                Some(json!({"actor_id":p.actor_id})),
            ))
        })(),
        _ => return None,
    })
}
fn run_path(id: Uuid, startup: bool) -> String {
    if startup {
        format!("/api/v1/startups/discovery/runs/{id}")
    } else {
        format!("/api/v1/discovery/runs/{id}")
    }
}
fn read_path(parent: Uuid, read: Uuid) -> String {
    format!("/api/v1/discovery/runs/{parent}/reads/{read}")
}
/// Errors echo only validated opaque identities, never query text/provider data/credentials.
pub(super) fn retained(name: &str, args: &Value) -> Value {
    if !(long_running(name)
        || matches!(
            name,
            "discovery_run_status" | "startup_discovery_status" | "apify_read_status"
        ))
    {
        return Value::Null;
    }
    let Some(id) = args["run_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .filter(|id| !id.is_nil())
    else {
        return Value::Null;
    };
    let mut value = json!({"run_id":id,"scope":if name.starts_with("startup_") {"startup_discovery"} else {"job_discovery"}});
    if name.starts_with("apify_read_") {
        let Some(read) = args["read_request_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .filter(|r| !r.is_nil() && *r != id)
        else {
            return Value::Null;
        };
        value["read_request_id"] = json!(read);
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    fn call(name: &str, args: Value) -> Result<Operation> {
        operation(name, args).expect("known tool")
    }
    #[test]
    fn catalog_defaults_expose_only_saved_reads_and_local_previews() {
        let tools = catalog(false, false);
        assert_eq!(tools.len(), 8);
        for tool in tools {
            let value = serde_json::to_value(tool).unwrap();
            assert_eq!(value["annotations"]["readOnlyHint"], true);
            assert_eq!(value["annotations"]["openWorldHint"], false);
        }
        for name in [
            "discovery_run",
            "startup_discovery_run",
            "discovery_complete",
            "apify_read_recover",
            "apify_read_complete",
            "startup_discovery_complete",
        ] {
            assert_eq!(
                authorize(name, false, true).unwrap_err().0,
                "mcp_capability_not_enabled"
            );
            assert!(authorize(name, true, false).is_ok());
        }
        for name in ["apify_inspect_actor", "apify_inspect_account"] {
            assert!(authorize(name, true, false).is_err());
            assert!(authorize(name, false, true).is_ok());
        }
    }
    #[test]
    fn enabled_catalog_distinguishes_local_completion_and_remote_inspection() {
        let tools = catalog(true, true);
        assert_eq!(tools.len(), 16);
        let mut names = std::collections::BTreeSet::new();
        for tool in tools {
            assert!(names.insert(tool.name.to_string()));
            let name = tool.name.to_string();
            let value = serde_json::to_value(tool).unwrap();
            if mutating(&name) {
                assert_eq!(value["annotations"]["readOnlyHint"], false);
                assert_eq!(
                    value["annotations"]["openWorldHint"],
                    !name.ends_with("_complete")
                );
                assert_eq!(value["annotations"]["idempotentHint"], !metadata(&name));
            }
        }
    }
    #[test]
    fn nested_schemas_resolve_and_exclude_alternate_identity_and_imports() {
        for tool in catalog(true, true) {
            let schema = Value::Object((*tool.input_schema).clone());
            let validator = jsonschema::validator_for(&schema).unwrap();
            if matches!(
                tool.name.as_ref(),
                "discovery_preview"
                    | "startup_discovery_preview"
                    | "discovery_run"
                    | "startup_discovery_run"
            ) {
                let mut value = json!({"request":{"source":"arbeitnow","query":{"limit":2}},"run_id":Uuid::new_v4(),"consent":true});
                if tool.name.ends_with("_preview") {
                    value.as_object_mut().unwrap().remove("run_id");
                    value.as_object_mut().unwrap().remove("consent");
                }
                assert!(validator.is_valid(&value), "{}", tool.name);
                value["request"]["idempotency_key"] = json!("alternate");
                assert!(!validator.is_valid(&value));
                value["request"]
                    .as_object_mut()
                    .unwrap()
                    .remove("idempotency_key");
                value["request"]["query"]["limit"] = json!(101);
                assert!(!validator.is_valid(&value));
            }
        }
    }
    #[test]
    fn original_puts_require_real_consent_original_uuid_and_native_normalization() {
        let id = Uuid::new_v4();
        for (name, startup) in [("discovery_run", false), ("startup_discovery_run", true)] {
            let args = json!({"run_id":id,"consent":true,"request":{"source":"arbeitnow","query":{"limit":2},"allow_paid":false}});
            let (method, path, body) = call(name, args.clone()).unwrap();
            assert_eq!(method, Method::PUT);
            assert_eq!(path, run_path(id, startup));
            let body = body.unwrap();
            assert_eq!(body["query"]["page"], 1);
            assert_eq!(body["allow_paid"], false);
            assert!(body["idempotency_key"].is_null());
            for key in [
                "idempotency_key",
                "manual_jobs",
                "companies",
                "permission_confirmed",
            ] {
                let mut changed = args.clone();
                changed["request"][key] = json!(null);
                assert!(call(name, changed).is_err());
            }
            for consent in [json!(false), json!("true"), json!(1), json!(null)] {
                let mut changed = args.clone();
                changed["consent"] = consent;
                assert!(call(name, changed).is_err());
            }
            let mut changed = args.clone();
            changed["run_id"] = json!(Uuid::nil());
            assert!(call(name, changed).is_err());
            let mut changed = args.clone();
            changed["request"]["allow_paid"] = json!("true");
            assert!(call(name, changed).is_err());
            let mut changed = args;
            changed["url"] = json!("https://example.invalid/private");
            assert!(call(name, changed).is_err());
        }
    }
    #[test]
    fn status_and_local_completion_never_map_to_recovery_or_start() {
        let id = Uuid::new_v4();
        let read = Uuid::new_v4();
        for (name, startup) in [
            ("discovery_run_status", false),
            ("startup_discovery_status", true),
        ] {
            let (method, path, body) = call(name, json!({"run_id":id})).unwrap();
            assert_eq!(method, Method::GET);
            assert_eq!(path, run_path(id, startup));
            assert!(body.is_none());
        }
        for name in ["discovery_complete", "startup_discovery_complete"] {
            let (method, path, body) = call(name, json!({"run_id":id})).unwrap();
            assert_eq!(method, Method::POST);
            assert!(path.ends_with("/complete"));
            assert_eq!(body, Some(json!({})));
            assert!(call(name, json!({"run_id":id,"request":{}})).is_err());
        }
        let (method, path, body) = call(
            "apify_read_complete",
            json!({"run_id":id,"read_request_id":read}),
        )
        .unwrap();
        assert_eq!(method, Method::POST);
        assert_eq!(path, format!("{}/complete", read_path(id, read)));
        assert_eq!(body, Some(json!({})));
        assert!(
            call(
                "apify_read_complete",
                json!({"run_id":id,"read_request_id":id})
            )
            .is_err()
        );
    }
    #[test]
    fn bounded_read_requires_distinct_opaque_identity_without_provider_targets() {
        let id = Uuid::new_v4();
        let read = Uuid::new_v4();
        let args = json!({"run_id":id,"read_request_id":read,"consent":true});
        let (method, path, body) = call("apify_read_recover", args.clone()).unwrap();
        assert_eq!(method, Method::PUT);
        assert_eq!(path, read_path(id, read));
        assert_eq!(body, Some(json!({})));
        for (key, value) in [
            ("read_request_id", json!(id)),
            ("consent", json!(false)),
            ("dataset_id", json!("injected")),
            ("url", json!("https://example.invalid")),
        ] {
            let mut changed = args.clone();
            changed[key] = value;
            assert!(call("apify_read_recover", changed).is_err());
        }
    }
    #[test]
    fn metadata_inspection_cannot_accept_actor_execution_fields_or_urls() {
        let (method, path, body) = call("apify_inspect_account", json!({"consent":true})).unwrap();
        assert_eq!(method, Method::POST);
        assert_eq!(path, "/api/v1/integrations/providers/apify/inspect");
        assert!(body.is_none());
        let (_, _, body) = call(
            "apify_inspect_actor",
            json!({"actor_id":"fictional~jobs","consent":true}),
        )
        .unwrap();
        assert_eq!(body, Some(json!({"actor_id":"fictional~jobs"})));
        for args in [
            json!({"actor_id":"https://example.invalid","consent":true}),
            json!({"actor_id":"fictional~jobs","consent":true,"input":{}}),
            json!({"actor_id":"fictional~jobs","consent":false}),
        ] {
            assert!(call("apify_inspect_actor", args).is_err());
        }
    }
    #[test]
    fn error_context_retains_only_validated_original_uuids() {
        let id = Uuid::new_v4();
        let read = Uuid::new_v4();
        let value = retained(
            "apify_read_recover",
            &json!({"run_id":id,"read_request_id":read,"query":"private query","token":"private"}),
        );
        assert_eq!(
            value,
            json!({"run_id":id,"read_request_id":read,"scope":"job_discovery"})
        );
        assert!(
            retained(
                "apify_read_recover",
                &json!({"run_id":id,"read_request_id":id})
            )
            .is_null()
        );
        assert!(
            retained(
                "apify_inspect_actor",
                &json!({"run_id":id,"actor_id":"private"})
            )
            .is_null()
        );
        assert!(retained("discovery_run", &json!({"run_id":"../../private"})).is_null());
    }
}
