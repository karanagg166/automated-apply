//! Public saved legacy Gmail status. Older sending grants never authorize a send action.
pub mod oauth;
pub mod refresh;
use crate::{
    Failure, Result,
    gmail_accounts::Settings,
    google_oauth::{self, GrantMode},
};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use std::collections::BTreeSet;
use uuid::Uuid;
pub const STATUS: &str = "/api/v1/integrations/gmail/status";
pub const SEND_BLOCKER: &str = "gmail_sending_disabled_by_owner_policy";
#[derive(Clone, Copy)]
pub enum Route {
    Status,
    SendRefusal,
}
impl Route {
    pub fn method(self) -> &'static str {
        match self {
            Self::Status => "GET",
            Self::SendRefusal => "POST",
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    if path == STATUS {
        return Some(Route::Status);
    }
    let tail = path.strip_prefix("/api/v1/outreach/drafts/")?;
    let (id, action) = tail.split_once('/')?;
    if !matches!(action, "send" | "send-preview") || id.parse::<Uuid>().is_err() {
        return None;
    }
    Some(Route::SendRefusal)
}
pub(crate) fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_legacy_database_error")
}
pub(crate) fn invalid() -> Failure {
    Failure("invalid_gmail_legacy_saved_record")
}
pub fn connect(mut value: Value) -> Result<Value> {
    use std::sync::LazyLock;
    static SCHEMA: LazyLock<Value> = LazyLock::new(|| {
        serde_json::from_str(include_str!("../schemas/gmail-legacy-connect.json"))
            .expect("frozen primary Gmail connect")
    });
    static VALIDATOR: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        jsonschema::draft202012::options()
            .should_validate_formats(true)
            .build(&SCHEMA)
            .expect("primary Gmail connect schema")
    });
    let invalid = || Failure("invalid_gmail_legacy_request");
    let body = value.as_object_mut().ok_or_else(invalid)?;
    body.entry("authorization_mode")
        .or_insert(json!("metadata"));
    body.entry("expected_email").or_insert(Value::Null);
    if let Some(email) = body.get_mut("expected_email").filter(|s| !s.is_null()) {
        *email = json!(
            crate::profile_contract::email(
                email
                    .as_str()
                    .ok_or_else(invalid)?
                    .trim_matches(crate::context_contract::python_space)
            )
            .map_err(|_| invalid())?
        );
    }
    if !VALIDATOR.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
#[derive(Clone, Copy)]
pub enum IoRoute {
    Connect,
    Verify,
    Disconnect,
}
pub fn io_route(path: &str) -> Option<IoRoute> {
    match path {
        "/api/v1/integrations/gmail/connect/start" => Some(IoRoute::Connect),
        "/api/v1/integrations/gmail/verify" => Some(IoRoute::Verify),
        "/api/v1/integrations/gmail/disconnect" => Some(IoRoute::Disconnect),
        _ => None,
    }
}
/// `value` is already a public-column projection, not a credential-bearing account row.
pub fn projection(
    value: Option<&Value>,
    authorized: bool,
    oauth_configured: bool,
) -> Result<Value> {
    let Some(value) = value else {
        return Ok(
            json!({"status":"not_connected","authorization_state":"not_connected","send_capability":"disabled_by_owner_policy","account":null,"live_verified":false,"verification_recorded":false,"verification_basis":"saved_record_not_current_probe","oauth_configured":oauth_configured,"sending_enabled":false,"permissions":{"read_metadata":false,"read_body":false,"send":false,"modify":false},"read_mail_enabled":false,"create_draft_enabled":false}),
        );
    };
    let id = value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let state = value["status"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 100)
        .ok_or_else(invalid)?;
    let subject = value["google_subject"].as_str().ok_or_else(invalid)?;
    let email = value["account_email"].as_str().ok_or_else(invalid)?;
    let scopes = value["granted_scopes"]
        .as_array()
        .filter(|a| a.len() <= 20)
        .ok_or_else(invalid)?
        .iter()
        .map(|s| {
            s.as_str()
                .filter(|s| s.len() <= 300)
                .map(str::to_owned)
                .ok_or_else(invalid)
        })
        .collect::<Result<BTreeSet<_>>>()?;
    let metadata = scopes == google_oauth::scopes(GrantMode::Metadata);
    let read = scopes == google_oauth::scopes(GrantMode::Read);
    let compose = scopes == google_oauth::scopes(GrantMode::Compose);
    let connected = state == "connected" && authorized && !subject.is_empty();
    let authorization = if state != "connected" {
        state
    } else if !authorized {
        "account_not_authorized"
    } else if subject.is_empty() {
        "identity_verification_required"
    } else if metadata {
        "metadata_connected"
    } else if read {
        "readonly_connected"
    } else if compose {
        "compose_authorized"
    } else {
        "unexpected_or_insufficient_scopes"
    };
    Ok(
        json!({"id":id,"status":state,"account_email":if subject.is_empty(){Value::Null}else{json!(email)},"google_subject":if subject.is_empty(){Value::Null}else{json!(subject)},"granted_scopes":value["granted_scopes"],"workflow":"legacy","permissions":{"read_metadata":connected&&(metadata||read),"read_body":connected&&read,"send":false,"modify":false},"permissions_basis":"saved_oauth_grant_only","connected_at":value["connected_at"],"last_verified_at":value["last_verified_at"],"last_refresh_at":value["last_refresh_at"],"authorization_state":authorization,"send_capability":"disabled_by_owner_policy","live_verified":false,"verification_recorded":state=="connected"&&!value["last_verified_at"].is_null(),"verification_basis":"saved_record_not_current_probe","oauth_configured":oauth_configured,"sending_enabled":false,"read_mail_enabled":false,"create_draft_enabled":false,"account_authorized":authorized}),
    )
}
pub async fn status(
    c: &mut PgConnection,
    settings: &Settings,
    oauth_configured: bool,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let ready: bool = sqlx::query_scalar("SELECT to_regclass('connected_accounts') IS NOT NULL")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if !ready {
        let mut value = projection(None, false, oauth_configured)?;
        value["schema_ready"] = json!(false);
        value["error_code"] = json!("gmail_legacy_schema_update_required");
        tx.commit()
            .await
            .map_err(|_| Failure("gmail_legacy_commit_outcome_unknown"))?;
        return Ok(value);
    }
    let accounts:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'status',status,'account_email',account_email,'google_subject',google_subject,'granted_scopes',granted_scopes,'connected_at',connected_at,'last_verified_at',last_verified_at,'last_refresh_at',last_refresh_at) FROM connected_accounts WHERE provider='gmail' ORDER BY id LIMIT 2").fetch_all(&mut *tx).await.map_err(db)?;
    if accounts.len() > 1 {
        return Err(Failure("gmail_legacy_identity_requires_review"));
    }
    let authorized = accounts
        .first()
        .and_then(|value| value["account_email"].as_str())
        .is_some_and(|email| settings.allows(email));
    let mut value = projection(accounts.first(), authorized, oauth_configured)?;
    value["schema_ready"] = json!(true);
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_legacy_commit_outcome_unknown"))?;
    Ok(value)
}
