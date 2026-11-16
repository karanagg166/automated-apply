//! Fixed role metadata and encrypted local drafts. Gmail IO is owned by separate services.
pub mod account;
pub mod contract;
use crate::{
    Failure, Result,
    account_tokens::TokenStore,
    gmail_accounts::{self, Settings},
};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub const PATH: &str = "/api/v1/integrations/gmail/workspace";
pub(crate) const ACCOUNT: &str = "gmail_drafts:account";
pub(crate) const DRAFT: &str = "gmail_draft:";
#[derive(Clone, Copy)]
pub enum Slot {
    ReadOne,
    ReadTwo,
    Outreach,
}
impl Slot {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "read_1" => Some(Self::ReadOne),
            "read_2" => Some(Self::ReadTwo),
            "outreach" => Some(Self::Outreach),
            _ => None,
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::ReadOne => "read_1",
            Self::ReadTwo => "read_2",
            Self::Outreach => "outreach",
        }
    }
}
#[derive(Clone, Copy)]
pub enum IoRoute {
    Connect(Slot),
    Disconnect,
}
pub fn io_route(path: &str) -> Option<IoRoute> {
    let tail = path.strip_prefix(PATH)?;
    if tail == "/outreach/disconnect" {
        return Some(IoRoute::Disconnect);
    }
    tail.strip_prefix("/accounts/")
        .and_then(|s| s.strip_suffix("/connect"))
        .and_then(Slot::parse)
        .map(IoRoute::Connect)
}
pub async fn start_read<P: crate::gmail_accounts::oauth::Provider>(
    c: &mut PgConnection,
    slot: Slot,
    input: Value,
    browser: &str,
    settings: &Settings,
    provider: &P,
) -> Result<Value> {
    if matches!(slot, Slot::Outreach) {
        return Err(Failure("invalid_gmail_workspace_contract"));
    }
    let input = contract::normalize(contract::Kind::Consent, input)?;
    if input["account_consent"] != true {
        return Err(Failure("gmail_account_consent_required"));
    }
    let mut tx = begin(c).await?;
    if !gmail_accounts::schema(&mut tx).await? {
        return Err(Failure("gmail_readonly_schema_update_required"));
    }
    let key = format!("gmail_workspace_slot:{}", slot.name());
    let id = if let Some(saved) = get(&mut tx, &key).await? {
        saved["account_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?
    } else {
        let id = Uuid::new_v4();
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO gmail_read_accounts(id,provider,google_subject,account_email,status,token_generation,granted_scopes,connected_at) VALUES($1,'gmail','',$2,'disconnected',1,'[]',clock_timestamp()) RETURNING id").bind(id).bind(format!("pending:{}",id.simple())).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack != Some(id) {
            return Err(Failure("gmail_workspace_write_ack_failed"));
        }
        put(&mut tx, &key, &json!({"account_id":id})).await?;
        id
    };
    let duplicate:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key IN ('gmail_workspace_slot:read_1','gmail_workspace_slot:read_2') AND key<>$1 AND value->>'account_id'=$2)").bind(&key).bind(id.to_string()).fetch_one(&mut *tx).await.map_err(db)?;
    if duplicate {
        return Err(Failure("gmail_workspace_role_identity_conflict"));
    }
    commit(tx).await?;
    crate::gmail_accounts::oauth::Service { settings, provider }
        .start(
            c,
            json!({"account_consent":true,"read_body":input["read_body"]}),
            Some(id),
            browser,
        )
        .await
}
#[derive(Clone, Copy)]
pub enum Route<'a> {
    Accounts,
    Drafts,
    Draft(&'a str),
}
impl Route<'_> {
    pub fn accepts(self, method: &str) -> bool {
        match self {
            Self::Accounts => method == "GET",
            Self::Drafts => matches!(method, "GET" | "POST"),
            Self::Draft(_) => method == "PUT",
        }
    }
}
pub fn route(path: &str) -> Option<Route<'_>> {
    let tail = path.strip_prefix(PATH)?;
    match tail {
        "/accounts" => Some(Route::Accounts),
        "/drafts" => Some(Route::Drafts),
        _ => tail
            .strip_prefix("/drafts/")
            .filter(|s| identity(s))
            .map(Route::Draft),
    }
}
pub fn identity(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
pub(crate) fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_workspace_database_error")
}
pub(crate) fn invalid() -> Failure {
    Failure("invalid_gmail_workspace_saved_record")
}
pub(crate) async fn get(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
pub(crate) async fn put(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack.as_ref() != Some(value) {
        return Err(Failure("gmail_workspace_write_ack_failed"));
    }
    Ok(())
}
pub(crate) async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(407006,1)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    Ok(tx)
}
pub(crate) async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_workspace_commit_outcome_unknown"))
}
pub(crate) fn store(settings: &Settings) -> Result<&TokenStore> {
    settings
        .store
        .as_ref()
        .ok_or(Failure("gmail_workspace_encryption_not_configured"))
}
fn draft_key(id: &str) -> Result<String> {
    if !identity(id) {
        return Err(Failure("invalid_gmail_workspace_contract"));
    }
    Ok(format!("{DRAFT}{id}"))
}
pub(crate) fn content(settings: &Settings, key: &str, value: &Value) -> Result<Value> {
    let raw = store(settings)?.decrypt(value["content"].as_str().ok_or_else(invalid)?, key)?;
    let raw = raw
        .as_str()
        .filter(|s| s.len() <= 100000)
        .ok_or_else(invalid)?;
    let content: Value = serde_json::from_str(raw).map_err(|_| invalid())?;
    if content.as_object().is_none_or(|o| o.len() != 3)
        || ["recipient", "subject", "body"]
            .iter()
            .any(|key| content[key].as_str().is_none())
        || value["content_hash"] != contract::digest(&content)
    {
        return Err(invalid());
    }
    Ok(content)
}
fn public_draft(settings: &Settings, key: &str, value: &Value) -> Result<Value> {
    if value["id"] != key.strip_prefix(DRAFT).ok_or_else(invalid)?
        || value["version"].as_i64().is_none_or(|n| n < 1)
        || !matches!(
            value["status"].as_str(),
            Some("local_draft" | "dispatching" | "unknown" | "saved_in_gmail")
        )
    {
        return Err(invalid());
    }
    let mut result = json!({});
    for key in [
        "id",
        "version",
        "status",
        "profile_version",
        "company",
        "role",
        "content_hash",
        "gmail_draft_id",
    ] {
        if let Some(value) = value.get(key) {
            result[key] = value.clone();
        }
    }
    result["content"] = content(settings, key, value)?;
    Ok(result)
}
async fn accounts(tx: &mut Transaction<'_, Postgres>, settings: &Settings) -> Result<Value> {
    if !gmail_accounts::schema(tx).await? {
        return Ok(
            json!({"schema_ready":false,"accounts":[{"slot":"read_1","status":"setup_required"},{"slot":"read_2","status":"setup_required"},{"slot":"outreach","status":"setup_required"}],"sending_enabled":false}),
        );
    }
    let slots:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE key IN ('gmail_workspace_slot:read_1','gmail_workspace_slot:read_2') ORDER BY key").fetch_all(&mut **tx).await.map_err(db)?;
    let mut accounts = Vec::new();
    let mut ids = std::collections::BTreeSet::new();
    for slot in ["read_1", "read_2"] {
        let mut status = if let Some((_, value)) = slots
            .iter()
            .find(|(key, _)| key == &format!("gmail_workspace_slot:{slot}"))
        {
            let id = value["account_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?;
            if !ids.insert(id) {
                return Err(Failure("gmail_workspace_role_identity_conflict"));
            }
            gmail_accounts::status_in(tx, id, settings).await?
        } else {
            json!({"status":"not_connected"})
        };
        status["slot"] = json!(slot);
        accounts.push(status);
    }
    // Project only public fields from the outreach account; never fetch its token envelopes.
    let saved:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('status',value->'status','account_email',value->'account_email','google_subject',value->'google_subject','generation',value->'generation','scopes',value->'scopes') FROM owner_preferences WHERE key=$1").bind(ACCOUNT).fetch_optional(&mut **tx).await.map_err(db)?;
    let mut outreach = saved.unwrap_or(json!({"status":"not_connected","generation":0}));
    outreach["slot"] = json!("outreach");
    outreach["workflow"] = json!("drafts_only");
    outreach["drafts_enabled"] = json!(settings.drafts);
    outreach["sending_enabled"] = json!(false);
    let authorized = outreach["account_email"]
        .as_str()
        .is_some_and(|email| settings.allows(email));
    let scopes = outreach["scopes"].as_array().and_then(|a| {
        a.iter()
            .map(|s| s.as_str().map(str::to_owned))
            .collect::<Option<std::collections::BTreeSet<_>>>()
    });
    let compose = scopes.as_ref()
        == Some(&crate::google_oauth::scopes(
            crate::google_oauth::GrantMode::Compose,
        ));
    outreach["permissions"] = json!({"drafts":settings.drafts&&outreach["status"]=="connected"&&authorized&&compose,"send":false,"read_mail":false});
    outreach
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("scopes");
    outreach["live_verified"] = json!(false);
    outreach["verification_basis"] = json!("saved_record_not_current_probe");
    accounts.push(outreach);
    Ok(json!({"schema_ready":true,"accounts":accounts,"sending_enabled":false}))
}
async fn drafts(tx: &mut Transaction<'_, Postgres>, settings: &Settings) -> Result<Value> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,$1) ORDER BY created_at DESC,key LIMIT 100").bind(DRAFT).fetch_all(&mut **tx).await.map_err(db)?;
    let drafts = rows
        .iter()
        .map(|(key, value)| public_draft(settings, key, value))
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({"drafts":drafts}))
}
async fn save(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    id: Option<&str>,
    input: &Value,
) -> Result<Value> {
    let profile = crate::execution::reviewed_profile_in(tx)
        .await
        .map_err(|e| {
            if e.0 == "verified_profile_context_changed" {
                Failure("current_approved_profile_required")
            } else {
                e
            }
        })?;
    let id = id
        .map(str::to_owned)
        .unwrap_or_else(|| Uuid::new_v4().simple().to_string());
    let key = draft_key(&id)?;
    let old = get(tx, &key).await?.unwrap_or(json!({"version":0}));
    if old["version"] != input["expected_version"]
        || old.get("status").is_some_and(|s| s != "local_draft")
    {
        return Err(Failure("gmail_draft_version_or_state_conflict"));
    }
    let version = old["version"]
        .as_i64()
        .and_then(|v| v.checked_add(1))
        .filter(|v| *v > 0)
        .ok_or_else(invalid)?;
    let content = contract::content(input, &profile)?;
    let value = json!({"id":id,"version":version,"status":"local_draft","profile_version":profile["version"],"company":input["company"],"role":input["role"],"content_hash":contract::digest(&content),"content":store(settings)?.encrypt(&json!(crate::python_json::serialize(&content,false,true)),&key)?});
    put(tx, &key, &value).await?;
    public_draft(settings, &key, &value)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
) -> Result<Value> {
    if !route.accepts(method) {
        return Err(Failure("gmail_workspace_method_not_allowed"));
    }
    if query.is_some_and(|s| !s.is_empty()) {
        return Err(Failure("invalid_gmail_workspace_contract"));
    }
    if method == "GET" {
        if !body.is_empty() {
            return Err(Failure("invalid_gmail_workspace_contract"));
        }
        let mut tx = c.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let result = match route {
            Route::Accounts => accounts(&mut tx, settings).await?,
            Route::Drafts => drafts(&mut tx, settings).await?,
            _ => return Err(Failure("gmail_workspace_method_not_allowed")),
        };
        commit(tx).await?;
        return Ok(result);
    }
    let input = contract::normalize(
        contract::Kind::Draft,
        serde_json::from_slice(body).map_err(|_| Failure("invalid_gmail_workspace_contract"))?,
    )?;
    let mut tx = begin(c).await?;
    let result = save(
        &mut tx,
        settings,
        match route {
            Route::Draft(id) => Some(id),
            Route::Drafts => None,
            _ => return Err(Failure("gmail_workspace_method_not_allowed")),
        },
        &input,
    )
    .await?;
    commit(tx).await?;
    Ok(result)
}
