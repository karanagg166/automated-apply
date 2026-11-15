//! Source-attributed, bounded public feeds. Discovery confers no application authority.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use quick_xml::{Reader, events::Event};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use std::{
    collections::{BTreeMap, HashSet},
    time::Duration,
};
use uuid::Uuid;

const MAX_BYTES: usize = 4 * 1024 * 1024;
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    Himalayas,
    WeWorkRemotely,
}
impl Platform {
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "himalayas" => Ok(Self::Himalayas),
            "we_work_remotely" => Ok(Self::WeWorkRemotely),
            _ => Err(Failure("unsupported_public_feed")),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Himalayas => "himalayas",
            Self::WeWorkRemotely => "we_work_remotely",
        }
    }
    fn endpoint(self) -> &'static str {
        match self {
            Self::Himalayas => "https://himalayas.app/jobs/api?limit=20",
            Self::WeWorkRemotely => "https://weworkremotely.com/remote-jobs.rss",
        }
    }
    fn host(self) -> &'static str {
        match self {
            Self::Himalayas => "himalayas.app",
            Self::WeWorkRemotely => "weworkremotely.com",
        }
    }
    fn interval(self) -> i64 {
        match self {
            Self::Himalayas => 86400,
            Self::WeWorkRemotely => 1800,
        }
    }
    fn key(self) -> String {
        format!("public_feed:{}", self.name())
    }
}
pub fn route(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/rust-agent/platforms/")?
        .strip_suffix("/discover")
        .filter(|s| !s.is_empty() && !s.contains('/'))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    #[serde(default = "default_limit")]
    pub limit: usize,
}
fn default_limit() -> usize {
    20
}
pub fn request(body: &[u8]) -> Result<Input> {
    let value: Input =
        serde_json::from_slice(body).map_err(|_| Failure("invalid_public_feed_request"))?;
    if !(1..=20).contains(&value.limit) {
        return Err(Failure("invalid_public_feed_request"));
    }
    Ok(value)
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Job {
    pub source_id: String,
    pub title: String,
    pub company_name: Option<String>,
    /// Canonical attribution/deduplication identity; never use as an Apply override.
    pub source_url: String,
    /// Original validated provider link, including its query and fragment.
    pub application_url: String,
    pub description: String,
    pub description_truncated: bool,
    pub published_at: Option<String>,
    pub source_updated_at: Option<String>,
    pub expires_at: Option<String>,
    pub location_restrictions: Value,
    pub timezone_restrictions: Value,
    pub categories: Vec<String>,
    pub employment_type: Option<String>,
    pub applicant_count: Option<u32>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Batch {
    pub platform: Platform,
    pub jobs: Vec<Job>,
    pub has_more: bool,
    pub skipped_invalid: usize,
    pub duplicate_count: usize,
}
fn invalid() -> Failure {
    Failure("public_feed_response_invalid")
}
fn text(value: &Value, max: usize) -> Result<String> {
    let s = value
        .as_str()
        .filter(|s| !s.trim().is_empty() && s.chars().count() <= max)
        .ok_or_else(invalid)?;
    Ok(s.trim().into())
}
fn optional(value: &Value, max: usize) -> Result<Option<String>> {
    if value.is_null() {
        Ok(None)
    } else {
        text(value, max).map(Some)
    }
}
fn source_url(platform: Platform, s: &str) -> Result<String> {
    if s.bytes()
        .any(|b| b.is_ascii_control() || b.is_ascii_whitespace())
    {
        return Err(invalid());
    }
    let mut url = reqwest::Url::parse(s).map_err(|_| invalid())?;
    if url.scheme() != "https"
        || url.host_str() != Some(platform.host())
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port_or_known_default() != Some(443)
        || url.as_str().len() > 2048
    {
        return Err(invalid());
    }
    let valid = match platform {
        Platform::Himalayas => {
            url.path().starts_with("/companies/") || url.path().starts_with("/jobs/")
        }
        Platform::WeWorkRemotely => url.path().starts_with("/remote-jobs/"),
    };
    if !valid {
        return Err(invalid());
    }
    url.set_fragment(None);
    // Public discovery identifiers exclude tracking query parameters.
    url.set_query(None);
    Ok(url.into())
}
fn timestamp(value: &Value) -> Result<Option<String>> {
    if value.is_null() {
        return Ok(None);
    }
    let n = value.as_i64().ok_or_else(invalid)?;
    DateTime::<Utc>::from_timestamp(n, 0)
        .map(|d| Some(d.to_rfc3339()))
        .ok_or_else(invalid)
}
fn strings(value: &Value) -> Result<Vec<String>> {
    if value.is_null() {
        return Ok(vec![]);
    }
    value
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?
        .iter()
        .map(|v| text(v, 200))
        .collect()
}
fn restrictions(value: &Value) -> Result<Value> {
    if value.is_null() {
        return Ok(Value::Null);
    }
    if !value.is_array()
        || value.as_array().is_none_or(|a| a.len() > 300)
        || serde_json::to_vec(value).map_err(|_| invalid())?.len() > 12000
    {
        return Err(invalid());
    }
    Ok(value.clone())
}
pub fn himalayas(bytes: &[u8]) -> Result<Batch> {
    if bytes.len() > MAX_BYTES {
        return Err(Failure("public_feed_response_too_large"));
    }
    let raw: Value = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    let rows = raw["jobs"]
        .as_array()
        .filter(|a| a.len() <= 20)
        .ok_or_else(invalid)?;
    let mut batch = Batch {
        platform: Platform::Himalayas,
        jobs: vec![],
        has_more: raw.get("nextCursor").is_some_and(|c| !c.is_null()),
        skipped_invalid: 0,
        duplicate_count: 0,
    };
    let mut seen = HashSet::new();
    for row in rows {
        let parsed = (|| {
            let application_url = row["applicationLink"].as_str().ok_or_else(invalid)?;
            let canonical_url = source_url(Platform::Himalayas, application_url)?;
            Ok(Job {
                source_id: text(&row["guid"], 512)?,
                title: text(&row["title"], 255)?,
                company_name: optional(&row["companyName"], 255)?,
                source_url: canonical_url,
                application_url: application_url.into(),
                description: row["description"]
                    .as_str()
                    .unwrap_or("")
                    .chars()
                    .take(2048)
                    .collect(),
                description_truncated: row["description"]
                    .as_str()
                    .is_some_and(|s| s.chars().nth(2048).is_some()),
                // Himalayas documents pubDate as last updated, not original posting age.
                published_at: None,
                source_updated_at: timestamp(&row["pubDate"])?,
                expires_at: timestamp(&row["expiryDate"])?,
                location_restrictions: restrictions(&row["locationRestrictions"])?,
                timezone_restrictions: restrictions(&row["timezoneRestrictions"])?,
                categories: strings(&row["categories"])?,
                employment_type: optional(&row["employmentType"], 100)?,
                applicant_count: None,
            })
        })();
        match parsed {
            Ok(job) => {
                if seen.insert(job.source_url.clone()) {
                    batch.jobs.push(job);
                } else {
                    batch.duplicate_count += 1;
                }
            }
            Err(Failure(_)) => batch.skipped_invalid += 1,
        }
    }
    if !rows.is_empty() && batch.jobs.is_empty() {
        return Err(invalid());
    }
    Ok(batch)
}
#[derive(Default)]
struct RssItem {
    fields: BTreeMap<String, String>,
    description_truncated: bool,
}
impl RssItem {
    fn append(&mut self, key: &str, value: &str) -> Result<()> {
        let entry = self.fields.entry(key.into()).or_default();
        if key == "description" {
            // Retain a bounded preview even when a valid provider item embeds huge HTML.
            // XML tokens are still parsed and the complete response stays under MAX_BYTES.
            let remaining = 2048_usize.saturating_sub(entry.chars().count());
            let mut characters = value.chars();
            entry.extend(characters.by_ref().take(remaining));
            self.description_truncated |= characters.next().is_some();
        } else {
            if entry.len() + value.len() > 65536 {
                return Err(invalid());
            }
            entry.push_str(value);
        }
        Ok(())
    }
}
fn rss_job(item: RssItem) -> Result<Job> {
    let get = |key: &str| {
        item.fields
            .get(key)
            .map(String::as_str)
            .unwrap_or("")
            .trim()
    };
    let full = get("title");
    if full.is_empty() || full.chars().count() > 512 {
        return Err(invalid());
    }
    let (company, title) = full
        .split_once(": ")
        .map(|(a, b)| (Some(a.to_owned()), b.to_owned()))
        .unwrap_or((None, full.into()));
    if title.trim().is_empty() || title.chars().count() > 255 {
        return Err(invalid());
    }
    let url = source_url(Platform::WeWorkRemotely, get("link"))?;
    let date = if get("pubDate").is_empty() {
        None
    } else {
        Some(
            DateTime::parse_from_rfc2822(get("pubDate"))
                .map_err(|_| invalid())?
                .with_timezone(&Utc)
                .to_rfc3339(),
        )
    };
    let source_id = if get("guid").is_empty() {
        url.clone()
    } else {
        text(&json!(get("guid")), 512)?
    };
    Ok(Job {
        source_id,
        title,
        company_name: company,
        source_url: url,
        application_url: get("link").into(),
        description: get("description").chars().take(2048).collect(),
        description_truncated: item.description_truncated,
        published_at: date,
        source_updated_at: None,
        expires_at: None,
        location_restrictions: Value::Null,
        timezone_restrictions: Value::Null,
        categories: if get("category").is_empty() {
            vec![]
        } else {
            vec![get("category").chars().take(200).collect()]
        },
        employment_type: None,
        applicant_count: None,
    })
}
pub fn we_work_remotely(bytes: &[u8]) -> Result<Batch> {
    if bytes.len() > MAX_BYTES {
        return Err(Failure("public_feed_response_too_large"));
    }
    std::str::from_utf8(bytes).map_err(|_| invalid())?;
    let mut reader = Reader::from_reader(bytes);
    let mut stack: Vec<String> = vec![];
    let mut item: Option<RssItem> = None;
    let mut batch = Batch {
        platform: Platform::WeWorkRemotely,
        jobs: vec![],
        has_more: false,
        skipped_invalid: 0,
        duplicate_count: 0,
    };
    let mut seen = HashSet::new();
    let mut item_count = 0usize;
    let mut root = false;
    loop {
        let event = reader.read_event().map_err(|_| invalid())?;
        match event {
            Event::Start(e) => {
                let name = e.name().as_ref().to_owned();
                if stack.is_empty() {
                    if root || name != "rss" {
                        return Err(invalid());
                    }
                    root = true;
                }
                if stack.len() >= 24 {
                    return Err(invalid());
                }
                if name == "item" {
                    if item.is_some() || stack.last().map(String::as_str) != Some("channel") {
                        return Err(invalid());
                    }
                    item_count += 1;
                    if item_count > 1000 {
                        return Err(Failure("public_feed_item_limit"));
                    }
                    item = Some(RssItem::default());
                }
                stack.push(name);
            }
            Event::End(e) => {
                let name = e.name().as_ref().to_owned();
                if stack.pop().as_deref() != Some(name.as_str()) {
                    return Err(invalid());
                }
                if name == "item" {
                    match rss_job(item.take().ok_or_else(invalid)?) {
                        Ok(job) => {
                            if seen.insert(job.source_url.clone()) {
                                if batch.jobs.len() < 20 {
                                    batch.jobs.push(job);
                                } else {
                                    batch.has_more = true;
                                }
                            } else {
                                batch.duplicate_count += 1;
                            }
                        }
                        Err(_) => batch.skipped_invalid += 1,
                    }
                }
            }
            Event::Text(e) => {
                if let Some(item) = item.as_mut()
                    && stack.len() == 4
                {
                    let value: &str = e.as_ref();
                    item.append(&stack[3], value)?;
                }
            }
            Event::CData(e) => {
                if let Some(item) = item.as_mut()
                    && stack.len() == 4
                {
                    let value: &str = e.as_ref();
                    item.append(&stack[3], value)?;
                }
            }
            Event::GeneralRef(e) => {
                if let Some(item) = item.as_mut()
                    && stack.len() == 4
                {
                    let name: &str = e.as_ref();
                    let encoded = format!("&{name};");
                    let value = quick_xml::escape::unescape(&encoded).map_err(|_| invalid())?;
                    item.append(&stack[3], &value)?;
                }
            }
            Event::DocType(_) => return Err(Failure("public_feed_doctype_denied")),
            Event::Eof => break,
            _ => {}
        }
    }
    if !root || !stack.is_empty() || item.is_some() || item_count > 0 && batch.jobs.is_empty() {
        return Err(invalid());
    }
    Ok(batch)
}
pub async fn fetch(platform: Platform) -> Result<Batch> {
    let http = reqwest::Client::builder()
        .no_proxy()
        .retry(reqwest::retry::never())
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(4))
        .timeout(Duration::from_secs(12))
        .user_agent("AutomatedApply/0.1 public-job-discovery")
        .build()
        .map_err(|_| Failure("public_feed_transport_unavailable"))?;
    let mut response = http
        .get(platform.endpoint())
        .header(
            "Accept",
            match platform {
                Platform::Himalayas => "application/json",
                Platform::WeWorkRemotely => "application/rss+xml, application/xml, text/xml",
            },
        )
        .send()
        .await
        .map_err(|_| Failure("public_feed_unavailable"))?;
    if response.status().as_u16() == 429 {
        return Err(Failure("public_feed_rate_limited"));
    }
    if !response.status().is_success() {
        return Err(Failure("public_feed_unavailable"));
    }
    if response
        .content_length()
        .is_some_and(|n| n > MAX_BYTES as u64)
    {
        return Err(Failure("public_feed_response_too_large"));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| Failure("public_feed_unavailable"))?
    {
        if bytes.len() + chunk.len() > MAX_BYTES {
            return Err(Failure("public_feed_response_too_large"));
        }
        bytes.extend_from_slice(&chunk);
    }
    match platform {
        Platform::Himalayas => himalayas(&bytes),
        Platform::WeWorkRemotely => we_work_remotely(&bytes),
    }
}
pub enum Reservation {
    Cached(Value),
    Fetch { token: Uuid, record: Value },
}
fn db(_: sqlx::Error) -> Failure {
    Failure("public_feed_database_error")
}
fn epoch() -> i64 {
    Utc::now().timestamp()
}
fn output(batch: &Batch, limit: usize, fetched: i64, cached: bool) -> Result<Value> {
    let fetched = DateTime::<Utc>::from_timestamp(fetched, 0)
        .ok_or_else(invalid)?
        .to_rfc3339();
    Ok(
        json!({"platform":batch.platform,"attribution":batch.platform.host(),"source_endpoint":batch.platform.endpoint(),"fetched_at":fetched,"cached":cached,"jobs":batch.jobs.iter().take(limit).collect::<Vec<_>>(),"has_more":batch.has_more||batch.jobs.len()>limit,"skipped_invalid":batch.skipped_invalid,"duplicate_count":batch.duplicate_count,"scope":"public_feed_not_eligibility_or_application_verification","content_trust":"untrusted_source_data","application_dispatch":false,"saved_to_job_queue":false}),
    )
}
/// Reserve durably before network IO; crashes retain the cooldown and never replay immediately.
pub async fn reserve(
    connection: &mut PgConnection,
    platform: Platform,
    limit: usize,
) -> Result<Reservation> {
    let mut tx = connection.begin().await.map_err(db)?;
    let key = platform.key();
    sqlx::query(
        "INSERT INTO owner_preferences(key,value) VALUES($1,'{}') ON CONFLICT(key) DO NOTHING",
    )
    .bind(&key)
    .execute(&mut *tx)
    .await
    .map_err(db)?;
    let raw: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE")
            .bind(&key)
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    let now = epoch();
    if raw != json!({}) {
        let next = raw["next_allowed_at"]
            .as_i64()
            .ok_or(Failure("public_feed_saved_state_invalid"))?;
        if next > now {
            if raw["state"] == "completed" {
                let batch: Batch = serde_json::from_value(raw["batch"].clone())
                    .map_err(|_| Failure("public_feed_saved_state_invalid"))?;
                if batch.platform.name() != platform.name() || batch.jobs.len() > 20 {
                    return Err(Failure("public_feed_saved_state_invalid"));
                }
                let value = output(
                    &batch,
                    limit,
                    raw["fetched_at"]
                        .as_i64()
                        .ok_or(Failure("public_feed_saved_state_invalid"))?,
                    true,
                )?;
                tx.commit()
                    .await
                    .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
                return Ok(Reservation::Cached(value));
            }
            return Err(Failure("public_feed_cooldown"));
        }
    }
    let token = Uuid::new_v4();
    let record = json!({"token":token,"state":"fetching","started_at":now,"next_allowed_at":now+platform.interval()});
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 RETURNING value").bind(&key).bind(&record).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved != Some(record.clone()) {
        return Err(Failure("public_feed_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
    Ok(Reservation::Fetch { token, record })
}
pub async fn finish(
    connection: &mut PgConnection,
    platform: Platform,
    token: Uuid,
    mut record: Value,
    result: Result<Batch>,
    limit: usize,
) -> Result<Value> {
    if record["token"] != json!(token) || record["state"] != "fetching" {
        return Err(Failure("public_feed_saved_state_invalid"));
    }
    let prior = record.clone();
    let now = epoch();
    let response = match result {
        Ok(batch) => {
            record["state"] = json!("completed");
            record["fetched_at"] = json!(now);
            record["batch"] = json!(batch);
            output(&batch, limit, now, false)
        }
        Err(error) => {
            record["state"] = json!("failed");
            record["failure_code"] = json!(error.0);
            Err(error)
        }
    };
    let mut tx = connection.begin().await.map_err(db)?;
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$3,updated_at=clock_timestamp() WHERE key=$1 AND value=$2 RETURNING value").bind(platform.key()).bind(prior).bind(&record).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved != Some(record) {
        return Err(Failure("public_feed_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
    response
}
