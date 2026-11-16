//! One admitted draft POST; later explicit retries can only reconcile through bounded GETs.
use super::*;
use crate::{gmail_accounts::oauth::Provider, gmail_drafts::DraftClient};
use chrono::{DateTime, Duration, Utc};
#[allow(async_fn_in_trait)]
pub trait Client {
    async fn create(&self, raw: &[u8]) -> Result<Value>;
    async fn get(&self, id: &str) -> Result<Value>;
    async fn list(&self, query: &str) -> Result<Value>;
}
impl Client for DraftClient {
    async fn create(&self, raw: &[u8]) -> Result<Value> {
        self.create(raw).await
    }
    async fn get(&self, id: &str) -> Result<Value> {
        self.get(id).await
    }
    async fn list(&self, query: &str) -> Result<Value> {
        self.list(Some(query), 10).await
    }
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
fn at(value: &Value) -> Result<DateTime<Utc>> {
    crate::gmail_history::contract::timestamp(value)
        .map(|v| v.with_timezone(&Utc))
        .ok_or_else(invalid)
}
fn key(id: Uuid) -> String {
    format!("{DRAFT}{}", id.simple())
}
fn saved(value: &Value) -> Result<Value> {
    let id = text(value, "gmail_draft_id")?;
    crate::mailboxes::message_id(id)?;
    Ok(
        json!({"status":"saved_in_gmail","gmail_draft_id":id,"sent":false,"content_verified":value["content_verified"]==true,"verification_basis":"retained_draft_record_not_current_probe"}),
    )
}
async fn draft_in(tx: &mut Transaction<'_, Postgres>, id: Uuid, approval: &Value) -> Result<Value> {
    let draft = get(tx, &key(id))
        .await?
        .ok_or(Failure("gmail_draft_version_or_state_conflict"))?;
    if draft["id"] != id.simple().to_string()
        || draft["version"] != approval["expected_version"]
        || draft["content_hash"] != approval["content_hash"]
    {
        return Err(Failure("gmail_draft_version_or_state_conflict"));
    }
    Ok(draft)
}
async fn account_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    approval: &Value,
) -> Result<Value> {
    let account = get(tx, ACCOUNT)
        .await?
        .ok_or(Failure("gmail_drafts_account_not_connected"))?;
    account::valid(&account, settings)?;
    if account["generation"] != approval["expected_account_generation"] {
        return Err(Failure("gmail_drafts_account_changed"));
    }
    account::separate(
        tx,
        text(&account, "google_subject")?,
        text(&account, "account_email")?,
    )
    .await?;
    Ok(account)
}
async fn profile_in(tx: &mut Transaction<'_, Postgres>, draft: &Value) -> Result<()> {
    let profile = crate::execution::reviewed_profile_in(tx)
        .await
        .map_err(|error| {
            if error.0 == "verified_profile_context_changed" {
                Failure("gmail_draft_profile_changed_review_again")
            } else {
                error
            }
        })?;
    if profile["version"] != draft["profile_version"] {
        return Err(Failure("gmail_draft_profile_changed_review_again"));
    }
    Ok(())
}
fn binding(intent: &Value, draft: &Value, account: &Value) -> Result<()> {
    if intent["draft_id"] != draft["id"]
        || intent["key"] != draft["dispatch_intent"]
        || intent["draft_version"] != draft["version"]
        || intent["content_hash"] != draft["content_hash"]
        || intent["profile_version"] != draft["profile_version"]
        || intent["account_generation"] != account["generation"]
        || intent["account_subject"] != account["google_subject"]
        || intent["account_email"] != account["account_email"]
        || intent["post_admitted"] != true
        || intent["post_admissions"] != 1
    {
        return Err(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ));
    }
    Ok(())
}
struct Claim {
    draft: Value,
    account: Value,
    intent_key: String,
    raw: Option<Vec<u8>>,
    attempt: Uuid,
}
async fn precheck(
    c: &mut PgConnection,
    id: Uuid,
    approval: &Value,
    settings: &Settings,
) -> Result<Option<Value>> {
    if !settings.drafts {
        return Err(Failure("gmail_draft_creation_disabled"));
    }
    if approval["owner_reviewed"] != true {
        return Err(Failure("gmail_exact_draft_review_required"));
    }
    let mut tx = begin(c).await?;
    let draft = draft_in(&mut tx, id, approval).await?;
    let account = account_in(&mut tx, settings, approval).await?;
    if draft["status"] == "saved_in_gmail" {
        if draft["account_subject"] != account["google_subject"]
            || draft
                .get("account_generation")
                .is_some_and(|generation| generation != &account["generation"])
        {
            return Err(Failure("gmail_drafts_account_changed"));
        }
        let result = saved(&draft)?;
        commit(tx).await?;
        return Ok(Some(result));
    }
    if !matches!(
        draft["status"].as_str(),
        Some("local_draft" | "dispatching" | "unknown")
    ) {
        return Err(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ));
    }
    if draft["status"] == "local_draft"
        && [
            "dispatch_intent",
            "gmail_draft_id",
            "unconfirmed_gmail_draft_id",
        ]
        .iter()
        .any(|key| !draft[*key].is_null())
    {
        return Err(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ));
    }
    profile_in(&mut tx, &draft).await?;
    if draft["status"] != "local_draft" {
        let intent_key = draft["dispatch_intent"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or(Failure(
                "gmail_draft_dispatch_requires_manual_reconciliation",
            ))?;
        let intent = get(&mut tx, intent_key).await?.ok_or(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ))?;
        binding(&intent, &draft, &account)?;
    }
    commit(tx).await?;
    Ok(None)
}
async fn admit(
    c: &mut PgConnection,
    id: Uuid,
    approval: &Value,
    settings: &Settings,
    access: &account::Access,
) -> Result<Claim> {
    let attempt = Uuid::new_v4();
    let mut tx = begin(c).await?;
    let mut draft = draft_in(&mut tx, id, approval).await?;
    let account = account_in(&mut tx, settings, approval).await?;
    if account["generation"] != access.account["generation"]
        || account["google_subject"] != access.account["google_subject"]
        || account["account_email"] != access.account["account_email"]
    {
        return Err(Failure("gmail_drafts_account_changed"));
    }
    profile_in(&mut tx, &draft).await?;
    let content = super::content(settings, &key(id), &draft)?;
    let (intent_key, raw) = if draft["status"] == "local_draft" {
        let intent_key = format!("gmd_write:{}", Uuid::new_v4().simple());
        let marker = format!(
            "aa.workspace.{}@automated-apply.invalid",
            Uuid::new_v4().simple()
        );
        let raw = crate::mailboxes::mime_message(
            text(&account, "account_email")?,
            text(&content, "recipient")?,
            text(&content, "subject")?,
            text(&content, "body")?,
            &marker,
        )?;
        if raw.len() > 80000 {
            return Err(Failure("gmail_draft_request_limit"));
        }
        let intent = json!({"key":intent_key,"draft_id":draft["id"],"draft_version":draft["version"],"content_hash":draft["content_hash"],"profile_version":draft["profile_version"],"account_generation":account["generation"],"account_subject":account["google_subject"],"account_email":account["account_email"],"state":"dispatching","post_admitted":true,"post_admissions":1,"post_attempt":attempt,"post_until":Utc::now()+Duration::seconds(70),"message_id":marker,"read_admissions":0,"started_at":Utc::now()});
        put(&mut tx, &intent_key, &intent).await?;
        draft["dispatch_intent"] = json!(intent_key);
        draft["status"] = json!("dispatching");
        draft["account_subject"] = account["google_subject"].clone();
        draft["account_generation"] = account["generation"].clone();
        put(&mut tx, &key(id), &draft).await?;
        (intent_key, Some(raw))
    } else if matches!(draft["status"].as_str(), Some("dispatching" | "unknown")) {
        let intent_key = text(&draft, "dispatch_intent")?.to_owned();
        let intent = get(&mut tx, &intent_key).await?.ok_or_else(invalid)?;
        binding(&intent, &draft, &account)?;
        if !intent["post_until"].is_null() && at(&intent["post_until"])? > Utc::now() {
            return Err(Failure("gmail_draft_dispatch_in_progress"));
        }
        (intent_key, None)
    } else {
        return Err(Failure("gmail_draft_version_or_state_conflict"));
    };
    commit(tx).await?;
    Ok(Claim {
        draft,
        account,
        intent_key,
        raw,
        attempt,
    })
}
async fn unknown(c: &mut PgConnection, claim: &Claim, error: Failure) -> Result<()> {
    let mut tx = begin(c).await?;
    let mut intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    if intent["state"] == "verified" {
        return Ok(());
    }
    if (intent["state"] == "reading" || intent["state"] == "outcome_unknown")
        && intent["read_attempt"] != json!(claim.attempt)
        && intent["post_attempt"] != json!(claim.attempt)
    {
        return Ok(());
    }
    if intent["state"] == "reading" && intent["read_attempt"] != json!(claim.attempt) {
        return Ok(());
    }
    let mut draft = get(&mut tx, &format!("{DRAFT}{}", text(&claim.draft, "id")?))
        .await?
        .ok_or_else(invalid)?;
    if draft["dispatch_intent"] != claim.intent_key
        || draft["version"] != claim.draft["version"]
        || draft["content_hash"] != claim.draft["content_hash"]
    {
        return Err(Failure("gmail_draft_version_or_state_conflict"));
    }
    intent["state"] = json!("outcome_unknown");
    intent["last_failure_code"] = json!(error.0);
    intent["read_until"] = Value::Null;
    intent["post_until"] = Value::Null;
    draft["status"] = json!("unknown");
    draft["unknown_reason"] = json!(error.0);
    if let Some(id) = intent.get("provider_draft_id") {
        draft["unconfirmed_gmail_draft_id"] = id.clone();
    }
    put(&mut tx, &claim.intent_key, &intent).await?;
    put(
        &mut tx,
        &format!("{DRAFT}{}", text(&claim.draft, "id")?),
        &draft,
    )
    .await?;
    commit(tx).await
}
async fn retain_id(c: &mut PgConnection, claim: &Claim, id: &str) -> Result<()> {
    crate::mailboxes::message_id(id).map_err(|_| Failure("gmail_draft_creation_unconfirmed"))?;
    let mut tx = begin(c).await?;
    let mut intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    if intent["draft_id"] != claim.draft["id"]
        || intent["draft_version"] != claim.draft["version"]
        || intent["provider_draft_id"]
            .as_str()
            .is_some_and(|old| old != id)
    {
        return Err(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ));
    }
    intent["provider_draft_id"] = json!(id);
    intent["post_until"] = Value::Null;
    intent["provider_id_recorded_at"] = json!(Utc::now());
    put(&mut tx, &claim.intent_key, &intent).await?;
    commit(tx).await
}
async fn read_claim(
    c: &mut PgConnection,
    claim: &Claim,
    approval: &Value,
    settings: &Settings,
) -> Result<Value> {
    let mut tx = begin(c).await?;
    let draft = draft_in(
        &mut tx,
        text(&claim.draft, "id")?.parse().map_err(|_| invalid())?,
        approval,
    )
    .await?;
    let account = account_in(&mut tx, settings, approval).await?;
    profile_in(&mut tx, &draft).await?;
    let mut intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    binding(&intent, &draft, &account)?;
    if intent["state"] == "verified" {
        return Err(Failure("gmail_draft_already_verified"));
    }
    if !intent["read_until"].is_null() && at(&intent["read_until"])? > Utc::now() {
        return Err(Failure("gmail_draft_reconciliation_in_progress"));
    }
    let reads = intent["read_admissions"]
        .as_i64()
        .filter(|n| *n >= 0 && *n < 3)
        .ok_or(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ))?;
    intent["read_admissions"] = json!(reads + 1);
    intent["read_until"] = json!(Utc::now() + Duration::seconds(90));
    intent["state"] = json!("reading");
    intent["read_attempt"] = json!(claim.attempt);
    put(&mut tx, &claim.intent_key, &intent).await?;
    commit(tx).await?;
    Ok(intent)
}
async fn guard(
    c: &mut PgConnection,
    claim: &Claim,
    approval: &Value,
    settings: &Settings,
    read: &Value,
) -> Result<()> {
    let mut tx = begin(c).await?;
    let draft = draft_in(
        &mut tx,
        text(&claim.draft, "id")?.parse().map_err(|_| invalid())?,
        approval,
    )
    .await?;
    let account = account_in(&mut tx, settings, approval).await?;
    profile_in(&mut tx, &draft).await?;
    let intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    binding(&intent, &draft, &account)?;
    if intent["state"] != "reading"
        || intent["read_attempt"] != json!(claim.attempt)
        || intent["read_admissions"] != read["read_admissions"]
        || at(&intent["read_until"])? <= Utc::now()
    {
        return Err(Failure("gmail_draft_reconciliation_context_changed"));
    }
    commit(tx).await
}
async fn reconcile<C: Client>(
    c: &mut PgConnection,
    claim: &Claim,
    approval: &Value,
    settings: &Settings,
    client: &C,
) -> Result<Value> {
    let read = read_claim(c, claim, approval, settings).await?;
    guard(c, claim, approval, settings, &read).await?;
    let id = if let Some(id) = read["provider_draft_id"].as_str() {
        id.to_owned()
    } else {
        let page = client
            .list(&format!("rfc822msgid:{}", text(&read, "message_id")?))
            .await?;
        guard(c, claim, approval, settings, &read).await?;
        let records = page["drafts"]
            .as_array()
            .filter(|a| a.len() == 1)
            .ok_or(Failure("gmail_draft_creation_unconfirmed"))?;
        if page["nextPageToken"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
        {
            return Err(Failure("gmail_draft_creation_unconfirmed"));
        }
        text(&records[0], "id")?.to_owned()
    };
    crate::mailboxes::message_id(&id)?;
    guard(c, claim, approval, settings, &read).await?;
    let observed = client.get(&id).await?;
    if observed["id"] != id {
        return Err(Failure("gmail_draft_content_unverified"));
    }
    let content = super::content(
        settings,
        &format!("{DRAFT}{}", text(&claim.draft, "id")?),
        &claim.draft,
    )?;
    let headers = crate::mailboxes::verified_content(
        &observed["message"],
        text(&claim.account, "account_email")?,
        text(&content, "recipient")?,
        text(&content, "subject")?,
        text(&content, "body")?,
    )?;
    if headers.get("message-id").is_none_or(|value| {
        value.trim().trim_matches(['<', '>']) != read["message_id"].as_str().unwrap_or("")
    }) {
        return Err(Failure("gmail_draft_content_unverified"));
    }
    guard(c, claim, approval, settings, &read).await?;
    let mut tx = begin(c).await?;
    let mut draft = draft_in(
        &mut tx,
        text(&claim.draft, "id")?.parse().map_err(|_| invalid())?,
        approval,
    )
    .await?;
    let account = account_in(&mut tx, settings, approval).await?;
    profile_in(&mut tx, &draft).await?;
    let mut intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    binding(&intent, &draft, &account)?;
    if intent["state"] != "reading"
        || intent["read_attempt"] != json!(claim.attempt)
        || intent["read_admissions"] != read["read_admissions"]
        || at(&intent["read_until"])? <= Utc::now()
    {
        return Err(Failure("gmail_draft_reconciliation_context_changed"));
    }
    intent["state"] = json!("verified");
    intent["provider_draft_id"] = json!(id);
    intent["read_until"] = Value::Null;
    intent["verified_at"] = json!(Utc::now());
    draft["status"] = json!("saved_in_gmail");
    draft["gmail_draft_id"] = json!(id);
    draft["content_verified"] = json!(true);
    draft["verified_at"] = json!(Utc::now());
    draft
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("unknown_reason");
    draft
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("unconfirmed_gmail_draft_id");
    put(&mut tx, &claim.intent_key, &intent).await?;
    put(
        &mut tx,
        &format!("{DRAFT}{}", text(&claim.draft, "id")?),
        &draft,
    )
    .await?;
    let result = saved(&draft)?;
    commit(tx).await?;
    Ok(result)
}
async fn run<C: Client>(
    c: &mut PgConnection,
    mut claim: Claim,
    approval: &Value,
    settings: &Settings,
    client: &C,
) -> Result<Value> {
    if let Some(raw) = claim.raw.take() {
        if let Err(error) = post_guard(c, &claim, approval, settings).await {
            unknown(c, &claim, error).await?;
            return Err(error);
        }
        let result = client.create(&raw).await;
        let id = result.and_then(|value| text(&value, "id").map(str::to_owned));
        match id {
            Ok(id) => {
                if let Err(error) = retain_id(c, &claim, &id).await {
                    unknown(c, &claim, error).await?;
                    return Err(error);
                }
            }
            Err(error) => {
                unknown(c, &claim, error).await?;
                return Err(Failure("gmail_draft_creation_unconfirmed"));
            }
        }
    }
    match reconcile(c, &claim, approval, settings, client).await {
        Ok(value) => Ok(value),
        Err(error) => {
            if !matches!(
                error.0,
                "gmail_draft_reconciliation_in_progress" | "gmail_draft_already_verified"
            ) {
                unknown(c, &claim, error).await?;
            }
            Err(error)
        }
    }
}
async fn post_guard(
    c: &mut PgConnection,
    claim: &Claim,
    approval: &Value,
    settings: &Settings,
) -> Result<()> {
    let mut tx = begin(c).await?;
    let draft = draft_in(
        &mut tx,
        text(&claim.draft, "id")?.parse().map_err(|_| invalid())?,
        approval,
    )
    .await?;
    let account = account_in(&mut tx, settings, approval).await?;
    profile_in(&mut tx, &draft).await?;
    let intent = get(&mut tx, &claim.intent_key).await?.ok_or_else(invalid)?;
    binding(&intent, &draft, &account)?;
    if draft["status"] != "dispatching"
        || intent["state"] != "dispatching"
        || intent["post_attempt"] != json!(claim.attempt)
        || at(&intent["post_until"])? <= Utc::now()
    {
        return Err(Failure(
            "gmail_draft_dispatch_requires_manual_reconciliation",
        ));
    }
    commit(tx).await
}
impl<P: Provider> account::Service<'_, P> {
    pub async fn create_draft(
        &self,
        c: &mut PgConnection,
        id: Uuid,
        input: Value,
    ) -> Result<Value> {
        let approval = contract::normalize(contract::Kind::Approval, input)?;
        if let Some(result) = precheck(c, id, &approval, self.settings).await? {
            return Ok(result);
        }
        let access = self.access(c).await?;
        let client = self.settings.draft_client(access.token())?;
        let claim = admit(c, id, &approval, self.settings, &access).await?;
        run(c, claim, &approval, self.settings, &client).await
    }
    pub async fn create_draft_with_client<C: Client>(
        &self,
        c: &mut PgConnection,
        id: Uuid,
        input: Value,
        client: &C,
    ) -> Result<Value> {
        let approval = contract::normalize(contract::Kind::Approval, input)?;
        if let Some(result) = precheck(c, id, &approval, self.settings).await? {
            return Ok(result);
        }
        let access = self.access(c).await?;
        let claim = admit(c, id, &approval, self.settings, &access).await?;
        run(c, claim, &approval, self.settings, client).await
    }
}
