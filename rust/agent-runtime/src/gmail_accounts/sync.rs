//! Explicit selected bounded GETs; committed selection lease and atomic evidence/checkpoint.
use super::{
    oauth::{self, Provider, Service},
    refresh::Access,
    sync_rules, *,
};
use chrono::Duration;
#[allow(async_fn_in_trait)]
pub trait Reader {
    async fn messages(
        &self,
        labels: &[String],
        query: Option<&str>,
        page: Option<&str>,
    ) -> Result<Value>;
    async fn message(&self, id: &str, body: bool) -> Result<Value>;
}
impl Reader for crate::gmail_read::ReadClient {
    async fn messages(
        &self,
        labels: &[String],
        query: Option<&str>,
        page: Option<&str>,
    ) -> Result<Value> {
        self.messages(labels, query, page, 25).await
    }
    async fn message(&self, id: &str, body: bool) -> Result<Value> {
        self.message(id, body).await
    }
}
struct Claim {
    account: Uuid,
    generation: i64,
    lease: String,
    state: Value,
    policy: Value,
    window: sync_rules::Window,
    subject: String,
    email: String,
    granted: Value,
}
async fn claim(
    c: &mut PgConnection,
    access: &Access,
    id: Uuid,
    settings: &Settings,
) -> Result<Claim> {
    let mut tx = oauth::begin(c).await?;
    let current = account_in(&mut tx, id, true).await?;
    if current["status"] != "connected"
        || oauth::generation(&current)? != access.generation()?
        || current["google_subject"] != access.account["google_subject"]
        || current["account_email"] != access.account["account_email"]
    {
        return Err(Failure("gmail_sync_account_or_selection_changed"));
    }
    if !settings.allows(oauth::text(&current, "account_email")?) {
        return Err(Failure("gmail_account_not_authorized"));
    }
    let mut state = policy_in(&mut tx, id).await?;
    if state["policy"]["enabled"] != true {
        return Err(Failure("gmail_job_selection_required"));
    }
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if !state["lease_until"].is_null() && oauth::at(&state["lease_until"])? > now {
        return Err(Failure("gmail_sync_already_running"));
    }
    let mut raw = state["policy"].clone();
    raw["expected_version"] = state["version"].clone();
    let mut policy = contract::normalize(contract::Kind::Policy, raw)?;
    policy.as_object_mut().unwrap().remove("expected_version");
    let granted = scopes(&current)?;
    if granted != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Metadata)
        && granted != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Read)
    {
        return Err(Failure("gmail_readonly_scope_required"));
    }
    if policy["read_body"] == true
        && (!settings.body
            || granted != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Read))
    {
        return Err(Failure("gmail_body_access_review_required"));
    }
    if policy["retain_metadata"] == true && !settings.retention {
        return Err(Failure("gmail_local_retention_worker_required"));
    }
    let window = sync_rules::window(&policy, &state, now)?;
    state["window_start"] = json!(window.start);
    state["window_end"] = json!(window.end);
    state["status"] = json!("syncing");
    let lease = Uuid::new_v4().simple().to_string();
    state["lease_id"] = json!(lease);
    state["lease_until"] = json!(now + Duration::seconds(120));
    put(&mut tx, &format!("gmail_sync:{}", id.simple()), &state).await?;
    oauth::commit(tx).await?;
    Ok(Claim {
        account: id,
        generation: access.generation()?,
        lease,
        state,
        policy,
        window,
        subject: oauth::text(&current, "google_subject")?.to_owned(),
        email: oauth::text(&current, "account_email")?.to_owned(),
        granted: current["granted_scopes"].clone(),
    })
}
async fn guard(c: &mut PgConnection, claim: &Claim) -> Result<()> {
    let valid:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM gmail_read_accounts a JOIN owner_preferences p ON p.key=$2 WHERE a.id=$1 AND a.provider='gmail' AND a.status='connected' AND a.token_generation=$3 AND p.value->>'lease_id'=$4 AND p.value->'version'=$5 AND a.google_subject=$6 AND a.account_email=$7 AND a.granted_scopes::jsonb=$8 AND p.value->'policy'=$9 AND CASE WHEN pg_input_is_valid(p.value->>'lease_until','timestamp with time zone') THEN (p.value->>'lease_until')::timestamptz>clock_timestamp() ELSE false END)").bind(claim.account).bind(format!("gmail_sync:{}",claim.account.simple())).bind(claim.generation).bind(&claim.lease).bind(&claim.state["version"]).bind(&claim.subject).bind(&claim.email).bind(&claim.granted).bind(&claim.state["policy"]).fetch_one(c).await.map_err(db)?;
    if !valid {
        return Err(Failure("gmail_sync_account_or_selection_changed"));
    }
    Ok(())
}
struct Batch {
    state: Value,
    records: Vec<Value>,
    scanned: usize,
}
async fn collect<R: Reader>(
    c: &mut PgConnection,
    claim: &Claim,
    reader: &R,
    settings: &Settings,
) -> Result<Batch> {
    let mut state = claim.state.clone();
    let mut records = Vec::<Value>::new();
    let mut scanned = 0;
    let mut seen = BTreeSet::new();
    for _ in 0..claim.policy["max_pages"].as_u64().ok_or_else(invalid)? {
        let (labels, query, folder) = sync_rules::request(&claim.policy, &state, &claim.window)?;
        guard(c, claim).await?;
        let page = reader
            .messages(&labels, query.as_deref(), state["page_token"].as_str())
            .await?;
        if !page.is_object() {
            return Err(Failure("gmail_read_invalid_response"));
        }
        let entries = page.get("messages").cloned().unwrap_or(json!([]));
        let entries = entries
            .as_array()
            .filter(|a| a.len() <= 25)
            .ok_or(Failure("gmail_read_invalid_response"))?;
        let mut ids = Vec::new();
        for entry in entries {
            let id = entry["id"]
                .as_str()
                .ok_or(Failure("gmail_message_id_invalid"))?;
            crate::mailboxes::message_id(id)?;
            ids.push((
                id.to_owned(),
                format!(
                    "{:x}",
                    Sha256::digest(format!("{}:{id}", claim.account).as_bytes())
                )[..32]
                    .to_owned(),
            ));
        }
        let keys = ids
            .iter()
            .map(|(_, hash)| format!("gmail_msg:{hash}"))
            .collect::<Vec<_>>();
        let retained: Vec<String> =
            sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key=ANY($1::text[])")
                .bind(&keys)
                .fetch_all(&mut *c)
                .await
                .map_err(db)?;
        let retained = retained.into_iter().collect::<BTreeSet<_>>();
        for (id, digest) in ids {
            if retained.contains(&format!("gmail_msg:{digest}")) || !seen.insert(digest.clone()) {
                continue;
            }
            guard(c, claim).await?;
            let metadata = reader.message(&id, false).await?;
            scanned += 1;
            let Some(mut selected) = sync_rules::metadata(
                &metadata,
                &id,
                &claim.policy,
                &claim.window,
                folder.as_deref(),
            )?
            else {
                continue;
            };
            if claim.policy["read_body"] == true {
                guard(c, claim).await?;
                let message = reader.message(&id, true).await?;
                if message["id"] != id || message["threadId"] != metadata["threadId"] {
                    return Err(Failure("gmail_message_identity_mismatch"));
                }
                selected.evidence = crate::mail_evidence::content_evidence(&message["payload"])?;
            }
            let now = Utc::now();
            let mut record = selected.evidence;
            record["id"] = json!(digest);
            record["selection_version"] = claim.state["version"].clone();
            record["body_selected"] = claim.policy["read_body"].clone();
            record["account_id"] = json!(claim.account);
            record["message_id"] = json!(id);
            record["thread_id"] = json!(selected.thread);
            record["received_at"] = json!(selected.received);
            record["observed_at"] = json!(now);
            record["expires_at"] = json!(
                now + Duration::days(
                    claim.policy["retention_days"]
                        .as_i64()
                        .ok_or_else(invalid)?
                )
            );
            record["subject_digest"] =
                json!(format!("{:x}", Sha256::digest(selected.subject.as_bytes())));
            if claim.policy["retain_metadata"] == true {
                let headers = metadata["payload"]["headers"]
                    .as_array()
                    .ok_or_else(invalid)?;
                let header = |name: &str| {
                    headers
                        .iter()
                        .rev()
                        .find(|h| {
                            h["name"]
                                .as_str()
                                .is_some_and(|s| s.eq_ignore_ascii_case(name))
                        })
                        .map(|h| h["value"].clone())
                        .unwrap_or(json!(""))
                };
                let private = json!({"subject":selected.subject,"from":header("from"),"to":header("to"),"folder":folder,"received_at":selected.received});
                let encoded = crate::python_json::serialize(&private, false, true);
                record["encrypted_metadata"] = json!(
                    settings
                        .store
                        .as_ref()
                        .ok_or(Failure("oauth_encryption_not_configured"))?
                        .encrypt(&json!(encoded), &format!("gmail-metadata:{digest}"))?
                );
            }
            records.push(record);
        }
        let next = match page.get("nextPageToken") {
            None | Some(Value::Null) => None,
            Some(Value::String(s)) => Some(s.as_str()),
            _ => return Err(Failure("gmail_page_token_invalid")),
        };
        if !sync_rules::advance(&claim.policy, &mut state, next, &claim.window)? {
            break;
        }
    }
    state["status"] = json!(
        if state["page_token"].as_str().is_some_and(|s| !s.is_empty())
            || !state["window_end"].is_null()
        {
            "partial"
        } else {
            "completed"
        }
    );
    state["scanned"] = json!(scanned);
    state["last_error"] = Value::Null;
    Ok(Batch {
        state,
        records,
        scanned,
    })
}
async fn publish(
    c: &mut PgConnection,
    claim: &Claim,
    outcome: Result<Batch>,
    settings: &Settings,
) -> Result<Value> {
    let mut tx = oauth::begin(c).await?;
    let current = account_in(&mut tx, claim.account, true).await?;
    let mut state = policy_in(&mut tx, claim.account).await?;
    if current["status"] != "connected"
        || oauth::generation(&current)? != claim.generation
        || state["lease_id"] != claim.lease
        || state["version"] != claim.state["version"]
        || current["google_subject"] != claim.subject
        || current["account_email"] != claim.email
        || current["granted_scopes"] != claim.granted
        || state["policy"] != claim.state["policy"]
    {
        return Err(Failure("gmail_sync_account_or_selection_changed"));
    }
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let outcome = if oauth::at(&state["lease_until"])? <= now {
        Err(Failure("gmail_sync_lease_expired"))
    } else {
        outcome
    };
    let result = match outcome {
        Err(error) => {
            state["lease_id"] = Value::Null;
            state["lease_until"] = Value::Null;
            state["status"] = json!(if error.0 == "gmail_read_permission_required" {
                "reauthorization_required"
            } else {
                "failed"
            });
            state["last_error"] = json!(error.0);
            put(
                &mut tx,
                &format!("gmail_sync:{}", claim.account.simple()),
                &state,
            )
            .await?;
            Err(error)
        }
        Ok(mut batch) => {
            let mut inserted = 0;
            for record in batch.records {
                let id = oauth::text(&record, "id")?;
                let key = format!("gmail_msg:{id}");
                let existed: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)",
                )
                .bind(&key)
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
                if existed {
                    continue;
                }
                let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) RETURNING value").bind(&key).bind(&record).fetch_optional(&mut *tx).await.map_err(db)?;
                if saved.as_ref() != Some(&record) {
                    return Err(Failure("gmail_read_write_ack_failed"));
                }
                inserted += 1;
            }
            batch.state["inserted"] = json!(inserted);
            batch.state["scanned"] = json!(batch.scanned);
            batch.state["lease_id"] = Value::Null;
            batch.state["lease_until"] = Value::Null;
            batch.state["last_sync_at"] = json!(now);
            put(
                &mut tx,
                &format!("gmail_sync:{}", claim.account.simple()),
                &batch.state,
            )
            .await?;
            Ok(status_in(&mut tx, claim.account, settings).await?)
        }
    };
    oauth::commit(tx).await?;
    result
}
impl<P: Provider> Service<'_, P> {
    pub async fn sync(&self, c: &mut PgConnection, id: Uuid) -> Result<Value> {
        if !self.settings.sync {
            return Err(Failure("gmail_read_sync_disabled"));
        }
        let access = self.access(c, id).await?;
        let reader = crate::gmail_read::ReadClient::new(
            access.token(),
            self.settings.fixture,
            self.settings.endpoint.as_deref(),
        )?;
        self.sync_access(c, id, &access, &reader).await
    }
    /// Injectable fixed reader for isolated fixtures; all consent/fence rules stay shared.
    pub async fn sync_with_reader<R: Reader>(
        &self,
        c: &mut PgConnection,
        id: Uuid,
        reader: &R,
    ) -> Result<Value> {
        if !self.settings.sync {
            return Err(Failure("gmail_read_sync_disabled"));
        }
        let access = self.access(c, id).await?;
        self.sync_access(c, id, &access, reader).await
    }
    async fn sync_access<R: Reader>(
        &self,
        c: &mut PgConnection,
        id: Uuid,
        access: &Access,
        reader: &R,
    ) -> Result<Value> {
        let claim = claim(c, access, id, self.settings).await?;
        let outcome = tokio::time::timeout(
            std::time::Duration::from_secs(90),
            collect(c, &claim, reader, self.settings),
        )
        .await
        .unwrap_or(Err(Failure("gmail_sync_timeout")));
        publish(c, &claim, outcome, self.settings).await
    }
}
