//! Unified local preview/create and optional single-invocation grounded rewrite.
use super::*;
use super::{context::Context, drafts};
use sqlx::{Postgres, Transaction};
#[derive(Clone, Copy, PartialEq)]
pub enum Action {
    Preview,
    Create,
}
impl Action {
    fn name(self) -> &'static str {
        match self {
            Self::Preview => "preview",
            Self::Create => "create",
        }
    }
}
pub fn route(path: &str) -> Option<Action> {
    match path {
        "/api/v1/outreach/drafts/preview" => Some(Action::Preview),
        "/api/v1/outreach/drafts" => Some(Action::Create),
        _ => None,
    }
}
pub struct Service<'a> {
    pub contacts: &'a crate::contacts::Settings,
    pub answers: &'a crate::answer_service::Settings,
}
// A retained row cannot reconstruct this original in-process authority.
struct Invocation {
    key: String,
    journal: Value,
    input: Value,
    context: Context,
    action: Action,
}
enum Admission {
    Retained(Value),
    Original(Box<Invocation>),
}
fn conflict() -> Failure {
    Failure("outreach_generation_intent_conflict")
}
async fn journal_in(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    let row:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN jsonb_typeof(value::jsonb)='object' AND octet_length(value::text)<=65536 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(key).fetch_optional(&mut **tx).await.map_err(db)?;
    row.map(|v| v.ok_or_else(invalid)).transpose()
}
fn blocked(code: &'static str, retained: bool) -> Value {
    json!({"status":"needs_input","subject":null,"body":null,"requires_review":true,"missing_information":[code],"warnings":[],"unsupported_claim_flags":[],"error_code":code,"provider_metadata":{"used_llm":false},"evidence_references":[],"outbound_messages_sent":0,"sending_enabled":false,"retained_result":retained})
}
fn public_preview(value: Value) -> Result<Value> {
    let object = value.as_object().ok_or_else(invalid)?;
    if object.keys().any(|k| {
        ![
            "status",
            "subject",
            "body",
            "requires_review",
            "evidence_references",
            "missing_information",
            "unsupported_claim_flags",
            "warnings",
            "provider_metadata",
            "outbound_messages_sent",
            "sending_enabled",
            "retained_result",
            "error_code",
            "context_hash",
        ]
        .contains(&k.as_str())
    }) || value["requires_review"] != true
        || value["sending_enabled"] != false
        || value["outbound_messages_sent"] != 0
        || !matches!(
            value["status"].as_str(),
            Some("draft_ready" | "needs_input")
        )
    {
        return Err(invalid());
    }
    for (key, max) in [
        ("subject", 1020),
        ("body", 20000),
        ("error_code", 100),
        ("context_hash", 64),
    ] {
        if !value[key].is_null() && !value[key].as_str().is_some_and(|s| s.len() <= max) {
            return Err(invalid());
        }
    }
    if value["status"] == "draft_ready"
        && (value["subject"].as_str().is_none_or(str::is_empty)
            || value["body"].as_str().is_none_or(str::is_empty))
    {
        return Err(invalid());
    }
    for key in ["warnings", "missing_information", "unsupported_claim_flags"] {
        if !value[key].as_array().is_some_and(|a| {
            a.len() <= 100
                && a.iter()
                    .all(|v| v.as_str().is_some_and(|s| s.len() <= 2000))
        }) {
            return Err(invalid());
        }
    }
    if !value["evidence_references"].as_array().is_some_and(|a| {
        a.len() <= 200
            && a.iter().all(|r| {
                r.as_object().is_some_and(|o| {
                    o.len() == 2
                        && o.keys()
                            .all(|k| matches!(k.as_str(), "source_type" | "source_id"))
                }) && r["source_type"].as_str().is_some_and(|s| s.len() <= 100)
                    && r["source_id"].as_str().is_some_and(|s| s.len() <= 300)
            })
    }) {
        return Err(invalid());
    }
    let provider = value["provider_metadata"].as_object().ok_or_else(invalid)?;
    if provider
        .keys()
        .any(|k| !["provider", "model", "used_llm", "usage"].contains(&k.as_str()))
        || !value["provider_metadata"]["used_llm"].is_boolean()
    {
        return Err(invalid());
    }
    for key in ["provider", "model"] {
        let v = &value["provider_metadata"][key];
        if !v.is_null()
            && !v
                .as_str()
                .is_some_and(|s| s.len() <= 200 && !s.chars().any(char::is_control))
        {
            return Err(invalid());
        }
    }
    if let Some(usage) = provider.get("usage") {
        if !usage.is_null()
            && !usage.as_object().is_some_and(|o| {
                o.keys()
                    .all(|k| matches!(k.as_str(), "input_tokens" | "output_tokens"))
                    && o.values()
                        .all(|v| v.as_u64().is_some_and(|n| n <= 1_000_000_000))
            })
        {
            return Err(invalid());
        }
    }
    Ok(value)
}
impl Service<'_> {
    pub async fn run(
        &self,
        c: &mut PgConnection,
        input: Value,
        action: Action,
        origin: &str,
    ) -> Result<Value> {
        let input = contract::normalize(contract::Kind::Input, input)?;
        if !matches!(origin, "rest" | "mcp") {
            return Err(Failure("invalid_outreach_origin"));
        }
        if input["use_llm"] == false || origin == "mcp" {
            return if action == Action::Create {
                drafts::create_local(c, input, origin, self.contacts).await
            } else {
                Context::load(c, input.clone(), self.contacts)
                    .await?
                    .preview(input)
            };
        }
        let invocation = match self.admit(c, input, action).await? {
            Admission::Retained(value) => return Ok(value),
            Admission::Original(invocation) => *invocation,
        };
        // Refresh immediately before calling the governed writer, without taking control locks.
        let current = Context::load(c, invocation.input.clone(), self.contacts).await?;
        if current.digest() != invocation.context.digest() || !current.blockers.is_empty() {
            return self
                .finish(
                    c,
                    invocation,
                    blocked("outreach_generation_context_changed", false),
                )
                .await;
        }
        let first = invocation.context.facts.first().ok_or_else(invalid)?;
        let project = first["facts"].get("project").unwrap_or(&first["facts"]);
        let style = match invocation.input["writing_style"]
            .as_str()
            .ok_or_else(invalid)?
        {
            "friendly" => "conversational",
            "founder-focused" => "founder_focused",
            s => s,
        };
        let maximum = invocation.input["max_length"]
            .as_u64()
            .ok_or_else(invalid)? as usize;
        let question = format!(
            "Describe my project contribution to {} for an introduction to {}",
            line(project["name"].as_str().unwrap_or("my saved project")),
            line(
                invocation.context.contact["role_title"]
                    .as_str()
                    .ok_or_else(invalid)?
            )
        );
        let question = question.chars().take(2000).collect::<String>();
        let answer=crate::answer_service::generate(c,json!({"question":question,"writing_style":style,"max_characters":maximum.saturating_sub(800).max(100),"rewrite":true,"save_draft":false}),self.answers).await?;
        let mut result = if answer["status"] == "draft_ready" {
            let contribution = answer["answer"]
                .as_str()
                .filter(|s| !s.is_empty() && s.len() <= 20000)
                .ok_or_else(invalid)?;
            let references = answer["evidence_references"]
                .as_array()
                .filter(|a| !a.is_empty() && a.len() <= 100)
                .ok_or_else(invalid)?;
            if references.iter().any(|r| {
                !invocation
                    .context
                    .facts
                    .iter()
                    .any(|f| &f["reference"] == r)
            }) {
                blocked("outreach_writer_reference_outside_selected_context", false)
            } else {
                let mut rendering = invocation.context.clone();
                let facts = &mut rendering.facts.first_mut().ok_or_else(invalid)?["facts"];
                if facts.get("project").is_some() {
                    facts["project"]["contribution"] = json!(contribution);
                } else {
                    facts["contribution"] = json!(contribution);
                }
                let mut result = rendering.preview(invocation.input.clone())?;
                if result["status"] == "draft_ready" {
                    let refs = result["evidence_references"]
                        .as_array_mut()
                        .ok_or_else(invalid)?;
                    for reference in references {
                        if !refs.contains(reference) {
                            refs.push(reference.clone());
                        }
                    }
                }
                result
            }
        } else {
            let mut result = blocked("outreach_grounded_writer_did_not_produce_a_draft", false);
            if let Some(code) = answer["error_code"].as_str().filter(|s| {
                s.len() <= 100
                    && s.bytes()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
            }) {
                result["error_code"] = json!(code);
            }
            result
        };
        let mut provider = json!({"used_llm":answer["used_llm"].as_bool().unwrap_or(false)});
        for key in ["provider", "model"] {
            if let Some(value) = answer[key]
                .as_str()
                .filter(|s| s.len() <= 200 && !s.chars().any(char::is_control))
            {
                provider[key] = json!(value);
            }
        }
        if let Some(usage) = answer["usage"].as_object() {
            let mut safe = json!({});
            for key in ["input_tokens", "output_tokens"] {
                if let Some(n) = usage
                    .get(key)
                    .and_then(Value::as_u64)
                    .filter(|n| *n <= 1_000_000_000)
                {
                    safe[key] = json!(n);
                }
            }
            provider["usage"] = safe;
        }
        result["provider_metadata"] = provider;
        if answer["used_llm"] == true {
            result["warnings"]
                .as_array_mut()
                .ok_or_else(invalid)?
                .push(json!(
                    "Review every rewritten narrative claim against its saved evidence"
                ));
        }
        self.finish(c, invocation, result).await
    }
    async fn admit(&self, c: &mut PgConnection, input: Value, action: Action) -> Result<Admission> {
        let request = input["idempotency_key"]
            .as_str()
            .ok_or(Failure("outreach_writer_idempotency_key_required"))?;
        let key = format!(
            "outreach_gen:{}:{}",
            action.name(),
            fingerprint(&json!(request))
        );
        let hash = drafts::request_hash(&input, "rest");
        let mut tx = drafts::begin(c).await?;
        if action == Action::Create {
            if let Some(id) = sqlx::query_scalar::<_, Uuid>(
                "SELECT id FROM outreach_logs WHERE idempotency_key=$1",
            )
            .bind(request)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
            {
                let row = drafts::get_in(&mut tx, id, true).await?;
                if row["request_hash"] != hash {
                    return Err(Failure("outreach_idempotency_key_conflict"));
                }
                let result = drafts::read_in(&mut tx, &row, self.contacts).await?;
                tx.commit()
                    .await
                    .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
                return Ok(Admission::Retained(result));
            }
        }
        if let Some(record) = journal_in(&mut tx, &key).await? {
            if record["schema"] != 1
                || record["request_hash"] != hash
                || record["action"] != action.name()
                || record["input"] != input
            {
                return Err(conflict());
            }
            if record["state"] == "finding_retained" {
                let mut result = blocked("outreach_generation_result_requires_review", true);
                result["provider_metadata"] =
                    public_preview(record["proposal"].clone())?["provider_metadata"].clone();
                tx.commit()
                    .await
                    .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
                return Ok(Admission::Retained(result));
            }
            if record["state"] != "completed" {
                return Err(Failure("outreach_generation_reconciliation_required"));
            }
            let mut result = public_preview(record["result"].clone())?;
            if !result.is_object() || result.to_string().len() > 32768 {
                return Err(invalid());
            }
            let current = Context::load_in(&mut tx, &input, self.contacts, false).await?;
            if json!(current.digest()) != record["context_digest"] || !current.blockers.is_empty() {
                let provider = result["provider_metadata"].clone();
                result = blocked("outreach_generation_context_changed", true);
                result["provider_metadata"] = provider;
            } else {
                result["retained_result"] = json!(true);
            }
            tx.commit()
                .await
                .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
            return Ok(Admission::Retained(result));
        }
        let context = Context::load_in(&mut tx, &input, self.contacts, true).await?;
        let preview = context.preview(input.clone())?;
        if preview["status"] != "draft_ready" {
            tx.rollback().await.map_err(db)?;
            return Ok(Admission::Retained(preview));
        }
        let stamp = drafts::now_in(&mut tx).await?;
        let at = DateTime::parse_from_rfc3339(stamp.as_str().ok_or_else(invalid)?)
            .map_err(|_| invalid())?
            .to_utc();
        let journal = json!({"schema":1,"id":Uuid::new_v4(),"token":Uuid::new_v4(),"state":"admitted","writer_admissions":1,"action":action.name(),"request_hash":hash,"input":input,"context_digest":context.digest(),"started_at":stamp,"expires_at":(at+chrono::Duration::seconds(120)).to_rfc3339()});
        let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(&key).bind(&journal).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack.as_ref() != Some(&journal)
            || journal_in(&mut tx, &key).await?.as_ref() != Some(&journal)
        {
            return Err(Failure("outreach_write_ack_failed"));
        }
        tx.commit()
            .await
            .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
        Ok(Admission::Original(Box::new(Invocation {
            key,
            journal,
            input,
            context,
            action,
        })))
    }
    async fn finish(
        &self,
        c: &mut PgConnection,
        mut invocation: Invocation,
        proposal: Value,
    ) -> Result<Value> {
        if !proposal.is_object() || proposal.to_string().len() > 32768 {
            return Err(invalid());
        }
        let proposal = public_preview(proposal)?;
        // Preserve the returned model finding before any current-context/ledger transaction.
        let mut finding_tx = drafts::begin(c).await?;
        let original = journal_in(&mut finding_tx, &invocation.key)
            .await?
            .ok_or_else(conflict)?;
        if original != invocation.journal {
            return Err(conflict());
        }
        let mut finding = original.clone();
        finding["state"] = json!("finding_retained");
        finding["proposal"] = proposal.clone();
        finding["finding_at"] = drafts::now_in(&mut finding_tx).await?;
        let ack:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 AND value::jsonb=$3::jsonb RETURNING value").bind(&finding).bind(&invocation.key).bind(&original).fetch_optional(&mut *finding_tx).await.map_err(db)?;
        if ack.as_ref() != Some(&finding)
            || journal_in(&mut finding_tx, &invocation.key).await?.as_ref() != Some(&finding)
        {
            return Err(Failure("outreach_write_ack_failed"));
        }
        finding_tx
            .commit()
            .await
            .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
        invocation.journal = finding;
        let mut tx = drafts::begin(c).await?;
        let before = journal_in(&mut tx, &invocation.key)
            .await?
            .ok_or_else(conflict)?;
        if before != invocation.journal {
            return Err(conflict());
        }
        let context = Context::load_in(&mut tx, &invocation.input, self.contacts, true).await?;
        let stamp = drafts::now_in(&mut tx).await?;
        let now = DateTime::parse_from_rfc3339(stamp.as_str().ok_or_else(invalid)?)
            .map_err(|_| invalid())?
            .to_utc();
        let deadline =
            DateTime::parse_from_rfc3339(before["expires_at"].as_str().ok_or_else(invalid)?)
                .map_err(|_| invalid())?
                .to_utc();
        let current = context.digest() == invocation.context.digest()
            && context.blockers.is_empty()
            && now <= deadline;
        let result = if !current {
            let mut held = blocked("outreach_generation_context_changed", false);
            held["provider_metadata"] = proposal["provider_metadata"].clone();
            held
        } else if invocation.action == Action::Create && proposal["status"] == "draft_ready" {
            drafts::insert_in(
                &mut tx,
                &context,
                &invocation.input,
                &proposal,
                "rest",
                self.contacts,
            )
            .await?
        } else {
            proposal.clone()
        };
        let mut after = before.clone();
        after["state"] = json!("completed");
        after["finished_at"] = stamp;
        after["context_current_at_finish"] = json!(current);
        after["proposal"] = proposal;
        after["result"] = result.clone();
        if after.to_string().len() > 65536 {
            return Err(invalid());
        }
        let ack:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 AND value::jsonb=$3::jsonb RETURNING value").bind(&after).bind(&invocation.key).bind(&before).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack.as_ref() != Some(&after)
            || journal_in(&mut tx, &invocation.key).await?.as_ref() != Some(&after)
        {
            return Err(Failure("outreach_write_ack_failed"));
        }
        tx.commit()
            .await
            .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
        Ok(result)
    }
}
