//! Explicit inbox search and selected-body review; no raw bodies or mailbox content stored.
use super::*;
use crate::{gmail_read::ReadClient, mail_evidence};
#[derive(Clone)]
pub struct Search {
    pub query: String,
    pub limit: i64,
}
impl Search {
    pub fn parse(raw: Value) -> Result<Self> {
        let invalid = Failure("invalid_gmail_search");
        let object = raw.as_object().ok_or(invalid)?;
        if object
            .keys()
            .any(|key| !matches!(key.as_str(), "query" | "limit"))
        {
            return Err(invalid);
        }
        let query = raw
            .get("query")
            .map(|v| v.as_str().ok_or(invalid))
            .transpose()?
            .unwrap_or("Naukri newer_than:30d");
        if query.is_empty() || query.chars().count() > 500 {
            return Err(invalid);
        }
        let limit = crate::profile_contract::pagination_integer(
            raw.get("limit").cloned().unwrap_or(json!(3)),
            1,
            5,
        )
        .map_err(|_| invalid)?;
        Ok(Self {
            query: query.into(),
            limit,
        })
    }
}
pub fn message_id(id: &str) -> Result<()> {
    if id.is_empty()
        || id.len() > 200
        || !id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(Failure("gmail_message_id_invalid"));
    }
    Ok(())
}
impl<P: Provider> Service<'_, P> {
    pub(super) fn reader(&self, token: &str) -> Result<ReadClient> {
        ReadClient::new(
            token,
            self.settings.fixture,
            self.settings.read_endpoint.as_deref(),
        )
    }
    pub async fn search(&self, c: &mut PgConnection, slot: Slot, input: Search) -> Result<Value> {
        if !(1..=5).contains(&input.limit)
            || input.query.is_empty()
            || input.query.chars().count() > 500
        {
            return Err(Failure("invalid_gmail_search"));
        }
        let access = self.access(c, slot).await?;
        let generation = access.generation()?;
        let client = self.reader(access.token())?;
        let page = client
            .messages(&["INBOX".into()], Some(&input.query), None, input.limit)
            .await?;
        self.check(c, slot, generation).await?;
        let mut output = vec![];
        let messages = match page.get("messages") {
            None => &[][..],
            Some(value) => value
                .as_array()
                .map(Vec::as_slice)
                .ok_or(Failure("gmail_read_invalid_response"))?,
        };
        for item in messages.iter().take(input.limit as usize) {
            let id = item["id"]
                .as_str()
                .ok_or(Failure("gmail_message_id_invalid"))?;
            message_id(id)?;
            let message = client.message(id, false).await?;
            let mut tx = c.begin().await.map_err(db)?;
            self.fence(&mut tx, slot, generation).await?;
            if message["id"] != id
                || !message["labelIds"]
                    .as_array()
                    .is_some_and(|labels| labels.iter().any(|label| label == "INBOX"))
            {
                return Err(Failure("gmail_message_selection_changed"));
            }
            let key = format!(
                "gm54_selected:{}",
                &digest(&format!("{}:{generation}:{id}", slot.name()))[..32]
            );
            put(&mut tx,&key,&json!({"slot":slot.name(),"generation":generation,"message_id":id,"expires_at":expires(900)})).await?;
            commit(tx).await?;
            let mut summary = json!(mail_evidence::headers(&message));
            summary["id"] = json!(id);
            output.push(summary);
        }
        Ok(
            json!({"slot":slot.name(),"generation":generation,"messages":output,"bounded":true,"monitoring":false}),
        )
    }
    pub async fn read(&self, c: &mut PgConnection, slot: Slot, id: &str) -> Result<Value> {
        if !self.settings.body {
            return Err(Failure("gmail_body_access_review_required"));
        }
        let access = self.access(c, slot).await?;
        let generation = access.generation()?;
        message_id(id)?;
        let key = format!(
            "gm54_selected:{}",
            &digest(&format!("{}:{generation}:{id}", slot.name()))[..32]
        );
        let selected = read(c, &key, false)
            .await?
            .ok_or(Failure("gmail_recent_inbox_selection_required"))?;
        if selected["slot"] != slot.name()
            || selected["generation"] != generation
            || selected["message_id"] != id
            || !instant(&selected["expires_at"]).is_some_and(|t| t > Utc::now())
        {
            return Err(Failure("gmail_recent_inbox_selection_required"));
        }
        let message = self.reader(access.token())?.message(id, true).await?;
        self.check(c, slot, generation).await?;
        if message["id"] != id
            || !message["labelIds"]
                .as_array()
                .is_some_and(|labels| labels.iter().any(|label| label == "INBOX"))
        {
            return Err(Failure("gmail_message_selection_changed"));
        }
        let parsing = mail_evidence::content_evidence(&message["payload"])?;
        let headers = mail_evidence::headers(&message);
        let sender =
            mail_evidence::single_address(headers.get("from").map(String::as_str).unwrap_or(""));
        Ok(
            json!({"slot":slot.name(),"id":id,"headers":headers,"parsing":parsing,"origin":{"sender_domain_is_naukri":sender.is_some_and(|sender|sender.ends_with("@naukri.com")),"authenticated_origin_verified":false},"body_stored":false,"links_opened":false,"submission_confirmed":false}),
        )
    }
}
