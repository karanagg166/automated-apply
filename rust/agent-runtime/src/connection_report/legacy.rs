//! Existing private setup receipts. Parse bounded files and project fixed evidence fields.
use super::*;
use std::{
    fs::File,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
};

fn read(settings: &Settings, name: &str) -> Option<Value> {
    let path = settings.evidence_dir.as_ref()?.join(name);
    let file = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .ok()?;
    let meta = file.metadata().ok()?;
    if !meta.is_file()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
        || meta.len() > 65536
    {
        return None;
    }
    let mut bytes = Vec::new();
    file.take(65537).read_to_end(&mut bytes).ok()?;
    if bytes.len() > 65536 {
        return None;
    }
    serde_json::from_slice::<Value>(&bytes)
        .ok()
        .filter(Value::is_object)
}

fn authenticated(row: &mut Row, proof: &Value, basis: &'static str, cap: &'static str) {
    row.configuration_status = "configured";
    row.evidence("authenticated", basis, stored_time(&proof["verified_at"]));
    row.identity_verification = "saved_exact_project_evidence";
    row.capability_verification = cap;
    row.capabilities = json!([cap]);
    row.owner_authorization_required = false;
    row.blocker = None;
}

pub(super) fn core(settings: &Settings) -> [Row; 4] {
    let mut cli = Row::new(
        "Supabase CLI",
        "core",
        false,
        "Review the verification record for the isolated CLI profile.",
    );
    cli.state = "owner_authorization_required".into();
    cli.owner_authorization_required = true;
    cli.blocker = Some("isolated_cli_project_check_pending");
    if let Some(proof) = read(settings, "supabase-cli.private.json")
        && proof["project_ref"] == settings.project_ref
        && proof["cli_account_access_verified"] == true
        && proof["status"] == "ACTIVE_HEALTHY"
    {
        authenticated(
            &mut cli,
            &proof,
            "saved_isolated_cli_project_list",
            "management_metadata_only",
        );
    }
    let mcp = read(settings, "mcp.private.json").unwrap_or(Value::Null);
    let mut rows = [
        ("Codex Supabase MCP", "codex"),
        ("VS Code Supabase MCP", "vs code"),
        ("AGY Supabase MCP", "agy"),
    ]
    .map(|(name, client)| {
        let config = &mcp["client_configurations"][client];
        let mut row = Row::new(
            name,
            "core",
            config["configured"] == true,
            "Review the saved read-only setup evidence for this MCP client.",
        );
        row.state = if config["disabled"] == true {
            "disabled"
        } else {
            "owner_authorization_required"
        }
        .into();
        row.owner_authorization_required = config["disabled"] != true;
        row.blocker = Some("mcp_read_only_connection_unverified");
        row
    });
    let project = format!("https://{}.supabase.co", settings.project_ref);
    let codex_pinned = mcp["read_only_results"]["get_project_url"]["content"]
        .as_array()
        .is_some_and(|items| {
            items.iter().any(|item| {
                item["text"].as_str().is_some_and(|text| {
                    let text = text.trim();
                    text == project
                        || serde_json::from_str::<Value>(text)
                            .ok()
                            .is_some_and(|value| {
                                value.as_str() == Some(project.as_str()) || value["url"] == project
                            })
                })
            })
        });
    if mcp["state"] == "read_only_results_received"
        && mcp["project_url_observed"] == true
        && codex_pinned
    {
        authenticated(
            &mut rows[0],
            &mcp,
            "saved_codex_mcp_read_only_calls",
            "read_only_project_metadata",
        );
    }
    if let Some(proof) = read(settings, "current/vscode-mcp.private.json")
        .or_else(|| read(settings, "vscode-mcp.private.json"))
        && proof["state"] == "verified"
        && proof["project_url_observed"] == true
        && proof["read_only_tool"] == "get_project_url"
        && proof["discovered_tools"]
            .as_array()
            .is_some_and(|tools| !tools.is_empty())
        && (proof["project_ref"] == settings.project_ref
            || proof["project_ref"].is_null() && settings.project_ref == "luvdmwnlwaqgvfwlmlom")
    {
        authenticated(
            &mut rows[1],
            &proof,
            "saved_vscode_extension_verification",
            "read_only_project_metadata",
        );
    }
    let [codex, vscode, agy] = rows;
    [cli, codex, vscode, agy]
}

pub(super) fn agy(row: &mut Row, settings: &Settings) {
    if let Some(proof) = read(settings, "agy-auth.private.json")
        && proof["authenticated_read_verified"] == true
        && proof["num_turns"] == 0
    {
        row.configuration_status = "configured";
        row.evidence(
            "authenticated",
            "saved_cli_metadata_zero_turns",
            stored_time(&proof["verified_at"]),
        );
        row.identity_verification = "saved_cli_authentication";
        row.capability_verification = "authentication_metadata_only";
        row.capabilities = json!(["authentication_metadata"]);
    }
}
