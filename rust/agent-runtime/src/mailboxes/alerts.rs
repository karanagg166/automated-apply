//! Approved local mailbox alerts. Unknown vacancy facts remain dashboard questions.
use super::*;
use sqlx::{Postgres, Transaction};
pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_alert_database_error")
}
pub(super) fn invalid() -> Failure {
    Failure("invalid_gmail_alert_saved_record")
}
pub(super) fn at(value: &Value) -> Result<DateTime<Utc>> {
    super::instant(value).ok_or_else(invalid)
}
pub(super) async fn get(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
pub(super) async fn put(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("gmail_alert_write_ack_failed"));
    }
    Ok(())
}
pub(super) async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
pub(super) async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_alert_commit_outcome_unknown"))
}
pub(super) fn public(mut policy: Value, account: &Value) -> Result<Value> {
    if policy["version"].as_i64().is_none_or(|n| n < 0) {
        return Err(invalid());
    }
    let configured = policy["enabled"] == true;
    let enabled = configured
        && account["status"] == "connected"
        && account["generation"] == policy["generation"];
    for key in ["lease", "lease_until", "page_token"] {
        policy.as_object_mut().ok_or_else(invalid)?.remove(key);
    }
    policy["enabled"] = json!(enabled);
    policy["configured_enabled"] = json!(configured);
    policy["runtime_available"] = json!(true);
    policy["sender"] = json!(alert_rules::SENDER);
    policy["sending_enabled"] = json!(false);
    policy["links_opened"] = json!(false);
    Ok(policy)
}
pub async fn status(c: &mut PgConnection, slot: Slot, settings: &Settings) -> Result<Value> {
    let value:Value=sqlx::query_scalar("SELECT jsonb_build_object('policy',(SELECT value FROM owner_preferences WHERE key=$1),'account',(SELECT jsonb_build_object('status',value->'status','generation',value->'generation') FROM owner_preferences WHERE key=$2),'automation_state',coalesce((SELECT value->>'state' FROM owner_preferences WHERE key='naukri_automation'),'STOPPED'),'mode',coalesce((SELECT value->>'mode' FROM owner_preferences WHERE key='exec_config:naukri'),'REVIEW'))").bind(format!("gm54_alerts:{}",slot.name())).bind(slot.key()).fetch_one(c).await.map_err(db)?;
    let mut result = public(
        if value["policy"].is_null() {
            json!({"version":0,"enabled":false})
        } else {
            value["policy"].clone()
        },
        &value["account"],
    )?;
    result["runtime_available"] = json!(settings.alerts_available());
    result["automation_state"] = value["automation_state"].clone();
    result["polling_allowed"] = json!(
        result["enabled"] == true
            && settings.alerts_available()
            && value["automation_state"] == "RUNNING"
            && value["mode"] != "OFF"
    );
    Ok(result)
}
impl<P: Provider> Service<'_, P> {
    pub async fn configure_alerts(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        input: Value,
    ) -> Result<Value> {
        let input = alert_rules::policy(input)?;
        self.settings.enabled()?;
        if !self.settings.body {
            return Err(Failure("gmail_body_access_review_required"));
        }
        let mut tx = begin(c).await?;
        let account = self
            .fence(
                &mut tx,
                slot,
                input["expected_generation"].as_i64().ok_or_else(invalid)?,
            )
            .await?;
        let key = format!("gm54_alerts:{}", slot.name());
        let old = get(&mut tx, &key).await?.unwrap_or(json!({"version":0}));
        if old["version"] != input["expected_version"] {
            return Err(Failure("gmail_alert_policy_changed"));
        }
        let next = old["version"]
            .as_i64()
            .and_then(|n| n.checked_add(1))
            .ok_or_else(invalid)?;
        let mut value = if old["generation"] == input["expected_generation"] {
            old
        } else {
            json!({})
        };
        for(key,item)in json!({"version":next,"enabled":input["enabled"],"generation":input["expected_generation"],"account_email":account["account_email"],"interval_seconds":input["interval_seconds"],"next_check_at":null,"lease":null,"lease_until":null}).as_object().unwrap(){value[key]=item.clone();}
        put(&mut tx, &key, &value).await?;
        let result = public(value, &account)?;
        commit(tx).await?;
        Ok(result)
    }
}

#[allow(async_fn_in_trait)]
pub trait Reader {
    async fn messages(&self, query: &str, page: Option<&str>) -> Result<Value>;
    async fn message(&self, id: &str, body: bool) -> Result<Value>;
}
impl Reader for crate::gmail_read::ReadClient {
    async fn messages(&self, query: &str, page: Option<&str>) -> Result<Value> {
        self.messages(&["INBOX".into()], Some(query), page, 5).await
    }
    async fn message(&self, id: &str, body: bool) -> Result<Value> {
        self.message(id, body).await
    }
}
pub async fn due(c: &mut PgConnection, settings: &Settings) -> Result<Option<Slot>> {
    if !settings.alerts_available() {
        return Ok(None);
    }
    let rows:Vec<String>=sqlx::query_scalar("SELECT p.key FROM owner_preferences p JOIN owner_preferences a ON a.key='gm54_account:'||right(p.key,1) WHERE p.key IN ('gm54_alerts:1','gm54_alerts:2') AND p.value->>'enabled'='true' AND a.value->>'status'='connected' AND a.value->'generation'=p.value->'generation' AND EXISTS(SELECT 1 FROM owner_preferences WHERE key='naukri_automation' AND value->>'state'='RUNNING') AND (SELECT value->>'mode' FROM owner_preferences WHERE key='exec_config:naukri') IS DISTINCT FROM 'OFF' AND CASE WHEN p.value->>'next_check_at' IS NULL THEN true WHEN pg_input_is_valid(p.value->>'next_check_at','timestamp with time zone') THEN (p.value->>'next_check_at')::timestamptz<=clock_timestamp() ELSE true END AND CASE WHEN p.value->>'lease_until' IS NULL THEN true WHEN pg_input_is_valid(p.value->>'lease_until','timestamp with time zone') THEN (p.value->>'lease_until')::timestamptz<=clock_timestamp() ELSE true END ORDER BY coalesce(p.value->>'next_check_at',''),p.key LIMIT 1").fetch_all(c).await.map_err(db)?;
    rows.first()
        .map(|s| Slot::parse(s.rsplit(':').next().ok_or_else(invalid)?))
        .transpose()
}
struct Claim {
    slot: Slot,
    lease: String,
    version: i64,
    generation: i64,
    automation: i64,
    value: Value,
    subject: String,
    email: String,
}
enum Admission {
    Work(Claim),
    Idle(&'static str),
}
async fn claim<P: Provider>(
    c: &mut PgConnection,
    service: &Service<'_, P>,
    slot: Slot,
    force: bool,
) -> Result<Admission> {
    if !service.settings.alerts_available() {
        return Ok(Admission::Idle("disabled_or_paused"));
    }
    let mut tx = begin(c).await?;
    let authority = crate::execution::preparation_authority_in(&mut tx).await?;
    let key = format!("gm54_alerts:{}", slot.name());
    let Some(mut value) = get(&mut tx, &key).await? else {
        return Ok(Admission::Idle("disabled_or_paused"));
    };
    if authority["state"] != "RUNNING" || authority["mode"] == "OFF" || value["enabled"] != true {
        return Ok(Admission::Idle("disabled_or_paused"));
    }
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if !value["lease_until"].is_null() && at(&value["lease_until"])? > now {
        return Ok(Admission::Idle("leased"));
    }
    if !force && !value["next_check_at"].is_null() && at(&value["next_check_at"])? > now {
        return Ok(Admission::Idle("not_due"));
    }
    let version = value["version"]
        .as_i64()
        .filter(|n| *n > 0)
        .ok_or_else(invalid)?;
    let generation = value["generation"]
        .as_i64()
        .filter(|n| *n > 0)
        .ok_or_else(invalid)?;
    let account = service.fence(&mut tx, slot, generation).await?;
    let interval = value["interval_seconds"]
        .as_i64()
        .filter(|n| (900..=86400).contains(n))
        .ok_or_else(invalid)?;
    let lease = Uuid::new_v4().to_string();
    value["lease"] = json!(lease);
    value["lease_until"] = json!(now + Duration::seconds(180));
    value["next_check_at"] = json!(now + Duration::seconds(interval));
    if value["page_token"].as_str().is_none_or(str::is_empty) {
        let watermark = value
            .get("watermark")
            .map(|v| v.as_i64().ok_or_else(invalid))
            .transpose()?
            .unwrap_or(0);
        value["scan_after"] = json!(std::cmp::max(
            (now - Duration::days(30)).timestamp(),
            watermark.saturating_sub(86400)
        ));
        value["scan_until"] = json!(now.timestamp() + 1);
    }
    let automation = authority["revision"]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or_else(invalid)?;
    let subject = text(&account, "google_subject")?.to_owned();
    let email = text(&account, "account_email")?.to_owned();
    put(&mut tx, &key, &value).await?;
    commit(tx).await?;
    Ok(Admission::Work(Claim {
        slot,
        lease,
        version,
        generation,
        automation,
        value,
        subject,
        email,
    }))
}
async fn guard<P: Provider>(
    tx: &mut Transaction<'_, Postgres>,
    service: &Service<'_, P>,
    claim: &Claim,
) -> Result<Value> {
    let authority = crate::execution::preparation_authority_in(tx).await?;
    let value = get(tx, &format!("gm54_alerts:{}", claim.slot.name()))
        .await?
        .ok_or(Failure("gmail_alert_authority_changed"))?;
    if authority["state"] != "RUNNING"
        || authority["revision"] != json!(claim.automation)
        || authority["mode"] == "OFF"
        || value["enabled"] != true
        || value["version"] != json!(claim.version)
        || value["lease"] != claim.lease
        || at(&value["lease_until"])? <= Utc::now()
    {
        return Err(Failure("gmail_alert_authority_changed"));
    }
    let account = service.fence(tx, claim.slot, claim.generation).await?;
    if account["google_subject"] != claim.subject || account["account_email"] != claim.email {
        return Err(Failure("gmail_account_changed"));
    }
    Ok(value)
}
async fn check<P: Provider>(
    c: &mut PgConnection,
    service: &Service<'_, P>,
    claim: &Claim,
) -> Result<()> {
    let mut tx = begin(c).await?;
    guard(&mut tx, service, claim).await?;
    commit(tx).await
}
fn count(result: &mut Value, key: &str, amount: usize) -> Result<()> {
    let old = result[key].as_u64().ok_or_else(invalid)?;
    result[key] = json!(old.checked_add(amount as u64).ok_or_else(invalid)?);
    Ok(())
}
async fn process<P: Provider, R: Reader>(
    c: &mut PgConnection,
    service: &Service<'_, P>,
    claim: &Claim,
    reader: &R,
    telegram: Option<&crate::telegram::Settings>,
    stage: &mut &'static str,
) -> Result<Value> {
    let mut result = json!({"messages":0,"listed_messages":0,"already_processed":0,"authenticated":0,"candidates_added":0,"direct_links":0,"rejected_origin":0,"rejected_topic":0,"without_direct_links":0,"submitted":false,"links_opened":false});
    *stage = "message_list";
    check(c, service, claim).await?;
    let page = reader
        .messages(
            &alert_rules::query(&claim.value)?,
            claim.value["page_token"].as_str(),
        )
        .await?;
    if !page.is_object() {
        return Err(Failure("gmail_alert_page_invalid"));
    }
    let messages = page.get("messages").cloned().unwrap_or(json!([]));
    let messages = messages
        .as_array()
        .filter(|a| a.len() <= 5)
        .ok_or(Failure("gmail_alert_page_invalid"))?;
    count(&mut result, "listed_messages", messages.len())?;
    for entry in messages {
        let message_id = entry["id"]
            .as_str()
            .ok_or(Failure("gmail_message_id_invalid"))?;
        crate::mailboxes::message_id(message_id)?;
        check(c, service, claim).await?;
        let key = format!(
            "gm54_alertmsg:{}",
            &digest(&format!("{}:{message_id}", claim.subject))[..32]
        );
        let seen: bool =
            sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)")
                .bind(&key)
                .fetch_one(&mut *c)
                .await
                .map_err(db)?;
        if seen {
            count(&mut result, "already_processed", 1)?;
            continue;
        }
        *stage = "message_metadata";
        let mut message = reader.message(message_id, false).await?;
        if message["id"] != message_id
            || !message["labelIds"]
                .as_array()
                .is_some_and(|a| a.contains(&json!("INBOX")))
        {
            return Err(Failure("gmail_message_selection_changed"));
        }
        count(&mut result, "messages", 1)?;
        let trusted = alert_rules::authenticated(&message);
        if trusted {
            let thread = message["threadId"].clone();
            crate::mailboxes::message_id(
                thread
                    .as_str()
                    .ok_or(Failure("gmail_message_selection_changed"))?,
            )?;
            check(c, service, claim).await?;
            *stage = "message_body";
            message = reader.message(message_id, true).await?;
            if message["id"] != message_id
                || message["threadId"] != thread
                || !message["labelIds"]
                    .as_array()
                    .is_some_and(|a| a.contains(&json!("INBOX")))
                || !alert_rules::authenticated(&message)
            {
                return Err(Failure("gmail_message_selection_changed"));
            }
            count(&mut result, "authenticated", 1)?;
        } else {
            count(&mut result, "rejected_origin", 1)?;
        }
        *stage = "candidate_publish";
        let mut tx = begin(c).await?;
        guard(&mut tx, service, claim).await?;
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        if trusted {
            if alert_rules::topic(&message) {
                let (added, links) = super::alert_candidates::retain(
                    &mut tx,
                    claim.slot,
                    &json!({"account_email":claim.email}),
                    &message,
                    now,
                    telegram,
                )
                .await?;
                count(&mut result, "candidates_added", added)?;
                count(&mut result, "direct_links", links)?;
                if links == 0 {
                    count(&mut result, "without_direct_links", 1)?;
                }
            } else {
                count(&mut result, "rejected_topic", 1)?;
            }
        }
        put(&mut tx,&key,&json!({"message_id":message_id,"generation":claim.generation,"origin_accepted":trusted,"processed_at":now,"body_stored":false})).await?;
        commit(tx).await?;
    }
    *stage = "cursor_publish";
    let mut tx = begin(c).await?;
    let mut value = guard(&mut tx, service, claim).await?;
    let next = match page.get("nextPageToken") {
        None | Some(Value::Null) => None,
        Some(Value::String(s))
            if s.len() <= 2048 && claim.value["page_token"].as_str() != Some(s.as_str()) =>
        {
            Some(s.as_str())
        }
        _ => return Err(Failure("gmail_alert_page_invalid")),
    };
    let more = next.is_some_and(|s| !s.is_empty());
    result["has_more_pages"] = json!(more);
    value["page_token"] = next.map(|s| json!(s)).unwrap_or(Value::Null);
    if !more {
        value["watermark"] = json!(claim.value["scan_until"].as_i64().ok_or_else(invalid)? - 1);
    }
    value["last_result"] = result.clone();
    value["last_check_at"] = json!(Utc::now());
    value["lease"] = Value::Null;
    value["lease_until"] = Value::Null;
    value["error"] = Value::Null;
    put(
        &mut tx,
        &format!("gm54_alerts:{}", claim.slot.name()),
        &value,
    )
    .await?;
    commit(tx).await?;
    result["status"] = json!("observed");
    Ok(result)
}
async fn failed(c: &mut PgConnection, claim: &Claim, error: Failure, stage: &str) -> Result<()> {
    let mut tx = begin(c).await?;
    let key = format!("gm54_alerts:{}", claim.slot.name());
    let Some(mut value) = get(&mut tx, &key).await? else {
        return Ok(());
    };
    if value["lease"] != claim.lease || value["version"] != json!(claim.version) {
        return Ok(());
    }
    value["lease"] = Value::Null;
    value["lease_until"] = Value::Null;
    value["page_token"] = Value::Null;
    value["error"] = json!("gmail_alert_cycle_failed");
    value["last_failure"] = json!({"code":error.0,"stage":stage,"at":Utc::now()});
    value["last_check_at"] = json!(Utc::now());
    put(&mut tx, &key, &value).await?;
    commit(tx).await
}
impl<P: Provider> Service<'_, P> {
    pub async fn poll_alerts(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        force: bool,
        telegram: Option<&crate::telegram::Settings>,
    ) -> Result<Value> {
        let claim = match claim(c, self, slot, force).await? {
            Admission::Idle(status) => return Ok(json!({"status":status,"submitted":false})),
            Admission::Work(claim) => claim,
        };
        let mut stage = "account_access";
        let outcome = tokio::time::timeout(std::time::Duration::from_secs(90), async {
            check(c, self, &claim).await?;
            let access = self.access(c, slot).await?;
            let reader = self.reader(access.token())?;
            process(c, self, &claim, &reader, telegram, &mut stage).await
        })
        .await
        .unwrap_or(Err(Failure("gmail_alert_cycle_timeout")));
        match outcome {
            Ok(value) => Ok(value),
            Err(error) => {
                failed(c, &claim, error, stage).await?;
                Err(error)
            }
        }
    }
    pub async fn poll_alerts_with_reader<R: Reader>(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        force: bool,
        reader: &R,
        telegram: Option<&crate::telegram::Settings>,
    ) -> Result<Value> {
        let claim = match claim(c, self, slot, force).await? {
            Admission::Idle(status) => return Ok(json!({"status":status,"submitted":false})),
            Admission::Work(claim) => claim,
        };
        let mut stage = "account_access";
        let outcome = tokio::time::timeout(std::time::Duration::from_secs(90), async {
            check(c, self, &claim).await?;
            self.access(c, slot).await?;
            process(c, self, &claim, reader, telegram, &mut stage).await
        })
        .await
        .unwrap_or(Err(Failure("gmail_alert_cycle_timeout")));
        match outcome {
            Ok(value) => Ok(value),
            Err(error) => {
                failed(c, &claim, error, stage).await?;
                Err(error)
            }
        }
    }
}
