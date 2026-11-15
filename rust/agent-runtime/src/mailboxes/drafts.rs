//! Exact owner-reviewed drafts with durable admission and readback; never sends mail.
use super::*;
use crate::{gmail_drafts::DraftClient, mail_evidence};
const TEST_SUBJECT: &str = "Automated Apply TEST - UNSENT read/draft acceptance";
const TEST_BODY: &str = "This is an owner-authorized Automated Apply connectivity test draft. It has not been sent. No application or candidate claims are included.";
pub struct ReviewedDraft {
    pub expected_generation: i64,
    pub request_id: Uuid,
    pub recipient: String,
    pub subject: String,
    pub body: String,
    pub content_hash: String,
    pub owner_reviewed: bool,
}
pub fn draft_hash(recipient: &str, subject: &str, body: &str) -> String {
    let body = format!(
        "{}\n",
        body.replace("\r\n", "\n")
            .replace('\r', "\n")
            .trim_end_matches('\n')
    );
    digest(&json!([folded(recipient), subject, body]).to_string())
}
pub fn expected_generation(raw: &Value) -> Result<i64> {
    crate::profile_contract::pagination_integer(raw["expected_generation"].clone(), 1, i64::MAX)
        .map_err(|_| Failure("invalid_gmail_draft_request"))
}
impl ReviewedDraft {
    pub fn parse(raw: Value) -> Result<Self> {
        let invalid = Failure("invalid_gmail_draft_request");
        let object = raw.as_object().ok_or(invalid)?;
        if object.keys().any(|key| {
            !matches!(
                key.as_str(),
                "expected_generation"
                    | "request_id"
                    | "recipient"
                    | "subject"
                    | "body"
                    | "content_hash"
                    | "owner_reviewed"
            )
        }) {
            return Err(invalid);
        }
        let recipient = crate::profile_contract::email(
            raw["recipient"]
                .as_str()
                .ok_or(invalid)?
                .trim_matches(crate::context_contract::python_space),
        )
        .map_err(|_| invalid)?;
        let subject = raw["subject"]
            .as_str()
            .filter(|s| {
                !s.is_empty()
                    && s.chars().count() <= 180
                    && !s.chars().any(|c| c.is_ascii_control())
            })
            .ok_or(invalid)?;
        let body = raw["body"]
            .as_str()
            .filter(|s| !s.is_empty() && s.chars().count() <= 10000)
            .ok_or(invalid)?;
        let hash = raw["content_hash"]
            .as_str()
            .filter(|s| {
                s.len() == 64
                    && s.bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            })
            .ok_or(invalid)?;
        Ok(Self {
            expected_generation: expected_generation(&raw)?,
            request_id: raw["request_id"]
                .as_str()
                .ok_or(invalid)?
                .parse()
                .map_err(|_| invalid)?,
            recipient,
            subject: subject.into(),
            body: body.into(),
            content_hash: hash.into(),
            owner_reviewed: raw["owner_reviewed"].as_bool().ok_or(invalid)?,
        })
    }
}
pub fn mime_message(
    from: &str,
    to: &str,
    subject: &str,
    body: &str,
    marker: &str,
) -> Result<Vec<u8>> {
    if [from, to, subject, marker]
        .iter()
        .any(|s| s.chars().any(|c| matches!(c, '\r' | '\n' | '\0')))
    {
        return Err(Failure("invalid_gmail_draft_request"));
    }
    let body = format!(
        "{}\n",
        body.replace("\r\n", "\n")
            .replace('\r', "\n")
            .trim_end_matches('\n')
    );
    mail_builder::MessageBuilder::new()
        .from(from)
        .to(to)
        .subject(subject)
        .message_id(marker)
        .text_body(body)
        .write_to_vec()
        .map_err(|_| Failure("gmail_draft_request_unconfirmed"))
}
pub fn verified_content(
    message: &Value,
    account: &str,
    recipient: &str,
    subject: &str,
    body: &str,
) -> Result<BTreeMap<String, String>> {
    let invalid = Failure("gmail_draft_content_unverified");
    let raw = message["payload"]["headers"].as_array().ok_or(invalid)?;
    if raw.len() > 100 {
        return Err(invalid);
    }
    for name in ["from", "to", "cc", "bcc", "subject", "message-id"] {
        if raw
            .iter()
            .filter(|header| header["name"].as_str().is_some_and(|s| folded(s) == name))
            .count()
            > 1
        {
            return Err(invalid);
        }
    }
    let mut headers = mail_evidence::headers(message);
    // Gmail can return RFC2047 words and folded headers. Decode the complete bounded
    // subject before comparing its exact reviewed content, rather than its UI preview.
    let raw_subject = raw
        .iter()
        .find(|h| {
            h["name"]
                .as_str()
                .is_some_and(|s| s.eq_ignore_ascii_case("subject"))
        })
        .and_then(|h| h["value"].as_str())
        .filter(|s| s.len() <= 8192)
        .ok_or(invalid)?;
    let raw_subject = raw_subject.trim_end_matches(['\r', '\n']);
    let bytes = raw_subject.as_bytes();
    if bytes.iter().enumerate().any(|(i, c)| match c {
        b'\r' => bytes.get(i + 1) != Some(&b'\n'),
        b'\n' => !bytes
            .get(i + 1)
            .is_some_and(|next| matches!(next, b' ' | b'\t')),
        _ => c.is_ascii_control() && *c != b'\t',
    }) {
        return Err(invalid);
    }
    let subject_header = format!("Subject: {raw_subject}\r\n\r\n");
    let parsed = mail_parser::MessageParser::default()
        .parse_headers(subject_header.as_bytes())
        .ok_or(invalid)?;
    let decoded_subject = parsed.subject().ok_or(invalid)?;
    headers.insert("subject".into(), decoded_subject.into());
    let encoded = message["payload"]["body"]["data"]
        .as_str()
        .filter(|s| s.len() <= 60000)
        .ok_or(invalid)?;
    let actual = mail_evidence::decoded_body(encoded, 45000).map_err(|_| invalid)?;
    let actual = String::from_utf8(actual).map_err(|_| invalid)?;
    let from = headers
        .get("from")
        .and_then(|s| mail_evidence::single_address(s));
    let to = headers
        .get("to")
        .and_then(|s| mail_evidence::single_address(s));
    let labels = message["labelIds"].as_array().ok_or(invalid)?;
    if !labels.iter().any(|v| v == "DRAFT")
        || labels.iter().any(|v| v == "SENT")
        || from.as_deref() != Some(account)
        || to.as_ref().is_none_or(|to| {
            draft_hash(
                to,
                headers.get("subject").map(String::as_str).unwrap_or(""),
                &actual,
            ) != draft_hash(recipient, subject, body)
        })
        || ["cc", "bcc"]
            .iter()
            .any(|name| headers.get(*name).is_some_and(|v| !v.is_empty()))
    {
        return Err(invalid);
    }
    Ok(headers)
}
impl<P: Provider> Service<'_, P> {
    fn drafts_client(&self, token: &str) -> Result<DraftClient> {
        DraftClient::new(
            token,
            self.settings.fixture,
            self.settings.read_endpoint.as_deref(),
        )
    }
    pub async fn drafts(&self, c: &mut PgConnection, slot: Slot) -> Result<Value> {
        let access = self.access(c, slot).await?;
        let page = self.drafts_client(access.token())?.list(None, 10).await?;
        self.check(c, slot, access.generation()?).await?;
        let drafts = page
            .get("drafts")
            .map(|v| v.as_array().ok_or(Failure("gmail_draft_response_invalid")))
            .transpose()?
            .cloned()
            .unwrap_or_default();
        Ok(
            json!({"drafts":drafts.into_iter().take(10).collect::<Vec<_>>(),"has_more":page["nextPageToken"].as_str().is_some_and(|s|!s.is_empty()),"sending_enabled":false}),
        )
    }
    pub async fn create_draft(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        input: ReviewedDraft,
    ) -> Result<Value> {
        if !self.settings.drafts {
            return Err(Failure("gmail_drafts_disabled"));
        }
        if !input.owner_reviewed
            || input.content_hash != draft_hash(&input.recipient, &input.subject, &input.body)
        {
            return Err(Failure("gmail_exact_draft_review_required"));
        }
        self.check(c, slot, input.expected_generation).await?;
        let access = self.access(c, slot).await?;
        let generation = access.generation()?;
        let mut tx = c.begin().await.map_err(db)?;
        self.fence(&mut tx, slot, input.expected_generation).await?;
        let key = format!(
            "gm54_draft:{}",
            &digest(&format!(
                "{}:{}",
                text(&access.account, "google_subject")?,
                input.request_id
            ))[..32]
        );
        let existing = read(&mut tx, &key, true).await?;
        let mut value = existing.clone().unwrap_or(json!({}));
        if existing.is_some() && value["content_hash"] != input.content_hash {
            return Err(Failure("gmail_draft_request_conflict"));
        }
        let client = self.drafts_client(access.token())?;
        if existing.is_some() {
            commit(tx).await?;
            if value["draft_id"].as_str().is_none_or(str::is_empty) {
                value["draft_id"] = json!(
                    self.reconcile_draft(
                        c,
                        slot,
                        &access,
                        &client,
                        &value,
                        "gmail_draft_outcome_unknown_inspect_gmail"
                    )
                    .await?
                );
            }
        } else {
            value = json!({"content_hash":input.content_hash,"message_id":format!("phase54.{}@automated-apply.invalid",Uuid::new_v4().simple()),"status":"dispatching"});
            let raw = mime_message(
                text(&access.account, "account_email")?,
                &input.recipient,
                &input.subject,
                &input.body,
                text(&value, "message_id")?,
            )?;
            put(&mut tx, &key, &value).await?;
            commit(tx).await?;
            self.check(c, slot, generation).await?;
            let result = client.create(&raw).await?;
            let id = result["id"]
                .as_str()
                .ok_or(Failure("gmail_draft_request_unconfirmed"))?;
            message_id(id).map_err(|_| Failure("gmail_draft_request_unconfirmed"))?;
            value["draft_id"] = json!(id);
            let mut tx = c.begin().await.map_err(db)?;
            self.fence(&mut tx, slot, generation).await?;
            put(&mut tx, &key, &value).await?;
            commit(tx).await?;
        }
        let id = text(&value, "draft_id")?.to_owned();
        let draft = client.get(&id).await?;
        let mut tx = c.begin().await.map_err(db)?;
        self.fence(&mut tx, slot, generation).await?;
        if draft["id"] != id {
            return Err(Failure("gmail_draft_content_unverified"));
        }
        verified_content(
            &draft["message"],
            text(&access.account, "account_email")?,
            &input.recipient,
            &input.subject,
            &input.body,
        )?;
        value["status"] = json!("verified");
        value["verified_at"] = json!(timestamp());
        put(&mut tx, &key, &value).await?;
        commit(tx).await?;
        Ok(
            json!({"draft_id":id,"draft_exists":true,"content_verified":true,"sending_enabled":false}),
        )
    }
    async fn reconcile_draft(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        access: &Access,
        client: &DraftClient,
        value: &Value,
        failure: &'static str,
    ) -> Result<String> {
        let query = format!("rfc822msgid:{}", text(value, "message_id")?);
        let page = client.list(Some(&query), 5).await?;
        self.check(c, slot, access.generation()?).await?;
        let drafts = page["drafts"]
            .as_array()
            .filter(|list| list.len() == 1)
            .ok_or(Failure(failure))?;
        let id = drafts[0]["id"].as_str().ok_or(Failure(failure))?;
        message_id(id).map_err(|_| Failure(failure))?;
        Ok(id.into())
    }
    pub async fn self_test_draft(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        expected: i64,
    ) -> Result<Value> {
        if !self.settings.drafts {
            return Err(Failure("gmail_drafts_disabled"));
        }
        self.check(c, slot, expected).await?;
        let access = self.access(c, slot).await?;
        let mut tx = c.begin().await.map_err(db)?;
        self.fence(&mut tx, slot, expected).await?;
        let key = format!(
            "gm54_test:{}",
            &digest(&format!(
                "{}:draft-acceptance-v1",
                text(&access.account, "google_subject")?
            ))[..32]
        );
        let existing = read(&mut tx, &key, true).await?;
        let mut value = existing.clone().unwrap_or(json!({}));
        let client = self.drafts_client(access.token())?;
        if existing.is_some() {
            commit(tx).await?;
            if value["draft_id"].as_str().is_none_or(str::is_empty) {
                value["draft_id"] = json!(
                    self.reconcile_draft(
                        c,
                        slot,
                        &access,
                        &client,
                        &value,
                        "gmail_test_draft_outcome_unknown_inspect_gmail"
                    )
                    .await?
                );
            }
        } else {
            value = json!({"slot":slot.name(),"account_subject_hash":digest(text(&access.account,"google_subject")?),"status":"dispatching","message_id":format!("phase54.{}@automated-apply.invalid",Uuid::new_v4().simple()),"started_at":timestamp()});
            let account = text(&access.account, "account_email")?;
            let raw = mime_message(
                account,
                account,
                TEST_SUBJECT,
                TEST_BODY,
                text(&value, "message_id")?,
            )?;
            put(&mut tx, &key, &value).await?;
            commit(tx).await?;
            self.check(c, slot, access.generation()?).await?;
            let result = client.create(&raw).await?;
            let id = result["id"]
                .as_str()
                .ok_or(Failure("gmail_draft_request_unconfirmed"))?;
            message_id(id).map_err(|_| Failure("gmail_draft_request_unconfirmed"))?;
            value["draft_id"] = json!(id);
            value["status"] = json!("created");
            let mut tx = c.begin().await.map_err(db)?;
            self.fence(&mut tx, slot, access.generation()?).await?;
            put(&mut tx, &key, &value).await?;
            commit(tx).await?;
        }
        self.confirm_test(c, slot, &access, &key, value, &client)
            .await
    }
    async fn confirm_test(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        access: &Access,
        key: &str,
        mut value: Value,
        client: &DraftClient,
    ) -> Result<Value> {
        self.check(c, slot, access.generation()?).await?;
        let draft = client.get(text(&value, "draft_id")?).await?;
        self.check(c, slot, access.generation()?).await?;
        if draft["id"] != value["draft_id"] {
            return Err(Failure("gmail_test_draft_verification_failed"));
        }
        let account = text(&access.account, "account_email")?;
        let headers =
            verified_content(&draft["message"], account, account, TEST_SUBJECT, TEST_BODY)?;
        let id = headers
            .get("message-id")
            .and_then(|s| s.strip_prefix('<'))
            .and_then(|s| s.strip_suffix('>'))
            .filter(|s| {
                let parts = s.split('@').collect::<Vec<_>>();
                parts.len() == 2
                    && !parts[0].is_empty()
                    && parts[0].len() <= 200
                    && !parts[1].is_empty()
                    && parts[1].len() <= 200
                    && parts[0]
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"._+=/-".contains(&c))
                    && parts[1]
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b".-".contains(&c))
            })
            .ok_or(Failure("gmail_test_draft_verification_failed"))?;
        let markers = BTreeSet::from([text(&value, "message_id")?.to_owned(), id.to_owned()]);
        let reader = crate::gmail_read::ReadClient::new(
            access.token(),
            self.settings.fixture,
            self.settings.read_endpoint.as_deref(),
        )?;
        for marker in markers {
            let sent = reader
                .messages(
                    &["SENT".into()],
                    Some(&format!("rfc822msgid:{marker}")),
                    None,
                    1,
                )
                .await?;
            self.check(c, slot, access.generation()?).await?;
            if sent
                .get("messages")
                .is_some_and(|v| v.as_array().is_none_or(|messages| !messages.is_empty()))
            {
                return Err(Failure("gmail_test_message_found_in_sent"));
            }
        }
        value["status"] = json!("verified");
        value["verified_at"] = json!(timestamp());
        value["draft_exists"] = json!(true);
        value["provider_message_id"] = json!(id);
        value["content_verified"] = json!(true);
        value["sent_search_empty"] = json!(true);
        value["sending_enabled"] = json!(false);
        let mut tx = c.begin().await.map_err(db)?;
        self.fence(&mut tx, slot, access.generation()?).await?;
        put(&mut tx, key, &value).await?;
        commit(tx).await?;
        let mut output = json!({});
        for name in [
            "status",
            "draft_id",
            "verified_at",
            "draft_exists",
            "sent_search_empty",
            "sending_enabled",
        ] {
            output[name] = value[name].clone();
        }
        Ok(output)
    }
}
