//! Legacy read-account metadata, selected policy and retained evidence. Provider IO is separate.
pub mod contract;
pub mod oauth;
pub mod refresh;
use crate::{Failure, Result, account_tokens::TokenStore};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use uuid::Uuid;
pub const PATH: &str = "/api/v1/integrations/gmail/accounts";
#[derive(Clone, Copy)]
pub enum IoRoute {
    Connect,
    Verify(Uuid),
    Disconnect(Uuid),
}
pub fn io_route(path: &str) -> Option<IoRoute> {
    let tail = path.strip_prefix(PATH)?.strip_prefix('/')?;
    if tail == "connect/start" {
        return Some(IoRoute::Connect);
    }
    let (id, action) = tail.split_once('/')?;
    let id = id.parse().ok()?;
    match action {
        "verify" => Some(IoRoute::Verify(id)),
        "disconnect" => Some(IoRoute::Disconnect(id)),
        _ => None,
    }
}
const PUBLIC_ACCOUNT: &str = "SELECT jsonb_build_object('id',id,'provider',provider,'google_subject',google_subject,'account_email',account_email,'granted_scopes',granted_scopes,'status',status,'token_generation',token_generation,'token_expires_at',token_expires_at,'connected_at',connected_at,'last_verified_at',last_verified_at,'last_refresh_at',last_refresh_at) FROM gmail_read_accounts";
pub struct Settings {
    sync: bool,
    body: bool,
    allowed: BTreeSet<String>,
    store: Option<TokenStore>,
    ttl: i64,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let raw: Vec<String> = serde_json::from_str(
            values
                .get("GMAIL_LOCAL_ALLOWED_EMAILS")
                .map(String::as_str)
                .unwrap_or("[]"),
        )
        .map_err(|_| Failure("gmail_account_allowlist_invalid"))?;
        if raw.len() > 100 {
            return Err(Failure("gmail_account_allowlist_invalid"));
        }
        let allowed = raw
            .into_iter()
            .map(|s| {
                crate::profile_contract::email(&s)
                    .map(|s| automated_apply_domain::text::folded(&s))
                    .map_err(|_| Failure("gmail_account_allowlist_invalid"))
            })
            .collect::<Result<_>>()?;
        Ok(Self {
            sync: crate::configuration::boolean(values, "GMAIL_READ_SYNC_ENABLED", false)?,
            body: crate::configuration::boolean(values, "GMAIL_READ_BODY_REVIEWED", false)?,
            allowed,
            store: TokenStore::from_values(values)?,
            ttl: values
                .get("OAUTH_STATE_TTL_SECONDS")
                .map(String::as_str)
                .unwrap_or("600")
                .parse::<i64>()
                .ok()
                .filter(|n| (60..=900).contains(n))
                .ok_or(Failure("invalid_oauth_state_ttl"))?,
        })
    }
    fn allows(&self, email: &str) -> bool {
        self.allowed.is_empty()
            || self
                .allowed
                .contains(&automated_apply_domain::text::folded(email))
    }
}
#[derive(Clone, Copy)]
pub enum Route {
    Accounts,
    Status(Uuid),
    Selection(Uuid),
    Evidence(Uuid),
    Leads(Uuid),
}
impl Route {
    pub fn method(self) -> &'static str {
        if matches!(self, Self::Selection(_)) {
            "PUT"
        } else {
            "GET"
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    if path == PATH {
        return Some(Route::Accounts);
    }
    let tail = path.strip_prefix(PATH)?.strip_prefix('/')?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    let id = id.parse().ok()?;
    match action {
        "" => Some(Route::Status(id)),
        "selection" => Some(Route::Selection(id)),
        "evidence" => Some(Route::Evidence(id)),
        "leads" => Some(Route::Leads(id)),
        _ => None,
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Page {
    pub offset: i64,
    pub limit: i64,
}
impl Page {
    pub fn parse(query: Option<&str>) -> Result<Self> {
        let mut page = Self {
            offset: 0,
            limit: 25,
        };
        let Some(raw) = query else { return Ok(page) };
        if raw.len() > 256 {
            return Err(Failure("invalid_gmail_read_page"));
        }
        let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{raw}"))
            .map_err(|_| Failure("invalid_gmail_read_page"))?;
        let mut seen = BTreeSet::new();
        for (k, v) in url.query_pairs() {
            if !seen.insert(k.to_string()) {
                return Err(Failure("invalid_gmail_read_page"));
            }
            match k.as_ref() {
                "offset" => {
                    page.offset = crate::profile_contract::pagination_integer(json!(v), 0, 100000)
                        .map_err(|_| Failure("invalid_gmail_read_page"))?
                }
                "limit" => {
                    page.limit = crate::profile_contract::pagination_integer(json!(v), 1, 100)
                        .map_err(|_| Failure("invalid_gmail_read_page"))?
                }
                _ => return Err(Failure("invalid_gmail_read_page")),
            }
        }
        Ok(page)
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_read_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_gmail_read_saved_record")
}
async fn schema(tx: &mut Transaction<'_, Postgres>) -> Result<bool> {
    sqlx::query_scalar("SELECT to_regclass('gmail_read_accounts') IS NOT NULL AND to_regclass('gmail_read_oauth_states') IS NOT NULL").fetch_one(&mut **tx).await.map_err(db)
}
async fn account_in(tx: &mut Transaction<'_, Postgres>, id: Uuid, locked: bool) -> Result<Value> {
    let query = format!(
        "{PUBLIC_ACCOUNT} WHERE provider='gmail' AND id=$1{}",
        if locked { " FOR UPDATE" } else { "" }
    );
    sqlx::query_scalar(&query)
        .bind(id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("gmail_read_account_not_found"))
}
fn scopes(value: &Value) -> Result<BTreeSet<String>> {
    value["granted_scopes"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect()
}
async fn policy_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(format!("gmail_sync:{}", id.simple()))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    let value = value.unwrap_or(json!({"version":0,"status":"selection_required","policy":null}));
    if value["version"].as_i64().is_none_or(|n| n < 0) || !value.is_object() {
        return Err(invalid());
    }
    Ok(value)
}
async fn status_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    settings: &Settings,
) -> Result<Value> {
    let account = account_in(tx, id, false).await?;
    status_value(id, &account, settings, policy_in(tx, id).await?)
}
fn status_value(id: Uuid, account: &Value, settings: &Settings, mut sync: Value) -> Result<Value> {
    let scopes = scopes(account)?;
    let state = account["status"].as_str().ok_or_else(invalid)?;
    let email = account["account_email"].as_str().ok_or_else(invalid)?;
    let subject = account["google_subject"].as_str().ok_or_else(invalid)?;
    let authorized = settings.allows(email);
    let connected = state == "connected" && !subject.is_empty() && authorized;
    let read = scopes == crate::google_oauth::scopes(crate::google_oauth::GrantMode::Read);
    let metadata = scopes == crate::google_oauth::scopes(crate::google_oauth::GrantMode::Metadata);
    if sync["version"].as_i64().is_none_or(|n| n < 0) || !sync.is_object() {
        return Err(invalid());
    }
    for key in ["page_token", "lease_id", "lease_until"] {
        sync.as_object_mut().unwrap().remove(key);
    }
    Ok(
        json!({"id":id,"status":state,"account_email":if subject.is_empty(){Value::Null}else{json!(email)},"google_subject":if subject.is_empty(){Value::Null}else{json!(subject)},"granted_scopes":account["granted_scopes"],"workflow":"readonly","permissions":{"read_metadata":connected&&(metadata||read),"read_body":connected&&read,"send":false,"modify":false},"connected_at":account["connected_at"],"last_verified_at":account["last_verified_at"],"last_refresh_at":account["last_refresh_at"],"authorization_state":if state!="connected"{state}else if !authorized{"account_not_authorized"}else if read{"readonly_connected"}else if metadata{"metadata_connected"}else{"unexpected_or_insufficient_scopes"},"send_capability":"disabled_by_owner_policy","live_verified":false,"verification_recorded":state=="connected"&&!account["last_verified_at"].is_null(),"verification_basis":"saved_record_not_current_probe","account_authorized":authorized,"sync":sync,"sync_enabled":settings.sync,"body_access_reviewed":settings.body}),
    )
}
async fn put(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("gmail_read_write_ack_failed"));
    }
    Ok(())
}
async fn configure_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    policy: &Value,
    settings: &Settings,
) -> Result<Value> {
    let account = account_in(tx, id, true).await?;
    let scopes = scopes(&account)?;
    let read = crate::google_oauth::scopes(crate::google_oauth::GrantMode::Read);
    if policy["read_body"] == true && (scopes != read || !settings.body) {
        return Err(Failure("gmail_body_access_review_required"));
    }
    if scopes != read
        && scopes != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Metadata)
    {
        return Err(Failure("gmail_readonly_scope_required"));
    }
    let current = policy_in(tx, id).await?;
    if current["version"] != policy["expected_version"] {
        return Err(Failure("gmail_sync_version_conflict"));
    }
    let version = current["version"]
        .as_i64()
        .and_then(|n| n.checked_add(1))
        .ok_or_else(invalid)?;
    let mut saved = policy.clone();
    saved.as_object_mut().unwrap().remove("expected_version");
    let value = json!({"account_id":id,"version":version,"policy":saved,"status":if policy["enabled"]==true{"ready"}else{"disabled"},"window_start":null,"window_end":null,"checkpoint":null});
    put(tx, &format!("gmail_sync:{}", id.simple()), &value).await?;
    status_in(tx, id, settings).await
}
async fn evidence_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    page: Page,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Vec<Value>> {
    account_in(tx, id, false).await?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gmail_msg:') AND value->>'account_id'=$1 AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz>$2 ELSE false END ORDER BY created_at DESC,key OFFSET $3 LIMIT $4").bind(id.to_string()).bind(now).bind(page.offset).bind(page.limit).fetch_all(&mut **tx).await.map_err(db)?;
    let mut result = Vec::new();
    let mut bytes = 0;
    for mut row in rows {
        let identity = row["id"]
            .as_str()
            .filter(|s| crate::gmail_history::contract::identity(s))
            .ok_or_else(invalid)?
            .to_owned();
        let encrypted = row
            .as_object_mut()
            .ok_or_else(invalid)?
            .remove("encrypted_metadata");
        if let Some(encrypted) = encrypted.filter(|v| !v.is_null()) {
            let metadata = settings
                .store
                .as_ref()
                .ok_or(Failure("oauth_encryption_not_configured"))?
                .decrypt(
                    encrypted.as_str().ok_or_else(invalid)?,
                    &format!("gmail-metadata:{identity}"),
                )?;
            let metadata: Value = serde_json::from_str(metadata.as_str().ok_or_else(invalid)?)
                .map_err(|_| invalid())?;
            if !metadata.is_object() {
                return Err(invalid());
            }
            row["metadata"] = metadata;
        }
        bytes += serde_json::to_vec(&row).map_err(|_| invalid())?.len();
        if bytes > 4 * 1024 * 1024 {
            return Err(Failure("gmail_evidence_projection_limit"));
        }
        result.push(row);
    }
    Ok(result)
}
pub fn leads(account: Uuid, messages: &[Value]) -> Result<Vec<Value>> {
    let mut result = Vec::<Value>::new();
    let mut indices = HashMap::new();
    for message in messages {
        let id = message["id"].as_str().ok_or_else(invalid)?;
        let links = message["links"].as_array().ok_or_else(invalid)?;
        let imported = message.get("imported_leads").and_then(Value::as_object);
        let all_imports = imported
            .into_iter()
            .flat_map(|m| m.values())
            .map(|v| v.as_array().ok_or_else(invalid))
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .flatten()
            .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
            .collect::<Result<BTreeSet<_>>>()?;
        let legacy = message
            .get("imported_job_ids")
            .map(|v| v.as_array().ok_or_else(invalid))
            .transpose()?
            .into_iter()
            .flatten()
            .any(|v| v.as_str().is_none_or(|s| !all_imports.contains(s)));
        for url in links {
            let url = url.as_str().ok_or_else(invalid)?;
            let identity = format!("{:x}", Sha256::digest(format!("{account}{url}").as_bytes()))
                [..32]
                .to_owned();
            let index=*indices.entry(identity.clone()).or_insert_with(||{let index=result.len();result.push(json!({"id":identity,"url":url,"evidence_ids":[],"verification_status":"requires_review","confirmed_vacancy":false,"imported_job_ids":[],"import_state":"not_imported"}));index});
            let lead = &mut result[index];
            lead["evidence_ids"].as_array_mut().unwrap().push(json!(id));
            let mut jobs = lead["imported_job_ids"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
                .collect::<Result<BTreeSet<_>>>()?;
            if let Some(ids) = imported.and_then(|m| m.get(url)) {
                for value in ids.as_array().ok_or_else(invalid)? {
                    jobs.insert(value.as_str().ok_or_else(invalid)?.to_owned());
                }
            }
            let state = if !jobs.is_empty() {
                "imported"
            } else if legacy || lead["import_state"] == "legacy_message_import_unknown" {
                "legacy_message_import_unknown"
            } else {
                "not_imported"
            };
            lead["import_state"] = json!(state);
            lead["imported_job_ids"] = json!(jobs);
        }
    }
    Ok(result)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
) -> Result<Value> {
    if route.method() != method {
        return Err(Failure("gmail_read_method_not_allowed"));
    }
    let paged = matches!(route, Route::Evidence(_) | Route::Leads(_));
    if query.is_some() && !paged {
        return Err(Failure("invalid_gmail_read_page"));
    }
    let page = Page::parse(query)?;
    let input = if matches!(route, Route::Selection(_)) {
        Some(contract::normalize(
            contract::Kind::Policy,
            serde_json::from_slice(body).map_err(|_| Failure("invalid_gmail_read_contract"))?,
        )?)
    } else {
        None
    };
    let mut tx = c.begin().await.map_err(db)?;
    let result=async{
        if matches!(route,Route::Selection(_)){sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE").execute(&mut *tx).await.map_err(db)?;crate::execution::lock_owner_in(&mut tx).await?;sqlx::query("SELECT pg_advisory_xact_lock(407006,1)").execute(&mut *tx).await.map_err(db)?;}else{sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.map_err(db)?;}
        if !schema(&mut tx).await?{return if matches!(route,Route::Accounts){Ok(json!({"accounts":[],"workflow":"readonly","schema_ready":false,"error_code":"gmail_readonly_schema_update_required"}))}else{Err(Failure("gmail_readonly_schema_update_required"))};}
        match route{
            Route::Accounts=>{
                let accounts:Vec<Value>=sqlx::query_scalar(&format!("{PUBLIC_ACCOUNT} WHERE provider='gmail' ORDER BY connected_at,id LIMIT 1001")).fetch_all(&mut *tx).await.map_err(db)?;
                if accounts.len()>1000{return Err(Failure("gmail_read_account_inventory_limit"));}
                let ids=accounts.iter().map(|a|a["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)).collect::<Result<Vec<_>>>()?;
                let keys=ids.iter().map(|id|format!("gmail_sync:{}",id.simple())).collect::<Vec<_>>();
                let policies:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE key=ANY($1::text[])").bind(&keys).fetch_all(&mut *tx).await.map_err(db)?;
                let policies=policies.into_iter().collect::<HashMap<_,_>>();let mut result=Vec::new();
                for(id,account)in ids.into_iter().zip(accounts){let policy=policies.get(&format!("gmail_sync:{}",id.simple())).cloned().unwrap_or(json!({"version":0,"status":"selection_required","policy":null}));result.push(status_value(id,&account,settings,policy)?);}
                Ok(json!({"accounts":result,"workflow":"readonly","schema_ready":true}))
            }
            Route::Status(id)=>status_in(&mut tx,id,settings).await,
            Route::Selection(id)=>configure_in(&mut tx,id,input.as_ref().unwrap(),settings).await,
            Route::Evidence(id)|Route::Leads(id)=>{let now:DateTime<Utc>=sqlx::query_scalar("SELECT clock_timestamp()").fetch_one(&mut *tx).await.map_err(db)?;let evidence=evidence_in(&mut tx,id,page,settings,now).await?;Ok(if matches!(route,Route::Evidence(_)){json!({"evidence":evidence,"offset":page.offset,"limit":page.limit})}else{json!({"leads":leads(id,&evidence)?,"offset":page.offset,"limit":page.limit})})}
        }
    }.await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("gmail_read_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("gmail_read_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
