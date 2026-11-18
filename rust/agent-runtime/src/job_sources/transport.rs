//! Fixed public GET batches consume original grants. No cookies, redirects, retries or result URL reads.
use super::{
    access::Grant,
    plan::{Snapshot, Source, Target},
    records,
};
use crate::{Failure, Result, source_registry::Settings};
use chrono::{DateTime, Datelike, Utc};
use reqwest::{Client as Http, Url};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};
use tokio::time::Instant;
const RESPONSE_LIMIT: usize = 8 * 1024 * 1024;
const BATCH_LIMIT: usize = 8 * 1024 * 1024;
pub struct Client {
    http: Http,
    settings: Settings,
    fixture: Option<Url>,
}
pub(super) struct Outcome {
    pub(super) request: uuid::Uuid,
    pub(super) invocation: uuid::Uuid,
    pub(super) configuration: String,
    pub(super) finding: Value,
    pub(super) cooldown: Option<DateTime<Utc>>,
}
struct Work {
    source: Source,
    deadline: Instant,
    max_requests: usize,
    attempts: usize,
    responses: usize,
    bytes: usize,
    jobs: Vec<Option<Value>>,
    retained: usize,
    seen: BTreeMap<String, (String, Option<usize>)>,
    errors: BTreeSet<&'static str>,
    rejected: usize,
    duplicates: usize,
    next: Option<String>,
    state: &'static str,
    cooldown: Option<DateTime<Utc>>,
}
impl Work {
    fn push(&mut self, board: &str, raw: &Value, parsed: Result<Value>) -> Result<()> {
        if Instant::now() >= self.deadline {
            self.state = "outcome_unknown";
            return Err(Failure("public_job_batch_timeout"));
        }
        let job = match parsed {
            Ok(v) => v,
            Err(_) => {
                self.rejected += 1;
                self.errors.insert("public_job_record_invalid");
                return Ok(());
            }
        };
        fn database_text(v: &Value) -> bool {
            match v {
                Value::String(s) => !s.contains('\0'),
                Value::Array(a) => a.iter().all(database_text),
                Value::Object(o) => o.iter().all(|(k, v)| !k.contains('\0') && database_text(v)),
                _ => true,
            }
        }
        if !database_text(&job) {
            self.rejected += 1;
            self.errors.insert("public_job_record_invalid");
            return Ok(());
        }
        let identity = job["source_job_id"]
            .as_str()
            .or_else(|| job["canonical_url"].as_str())
            .ok_or(Failure("public_job_record_invalid"))?;
        let key = format!("{board}\0{identity}");
        let hash = crate::python_json::digest(raw);
        if let Some((prior, index)) = self.seen.get_mut(&key) {
            self.duplicates += 1;
            if prior != &hash || index.is_none() {
                self.rejected += 1;
                self.errors.insert("public_job_inconsistent_duplicate");
                if let Some(index) = index.take()
                    && let Some(prior) = self.jobs[index].take()
                {
                    self.retained = self.retained.saturating_sub(prior.to_string().len());
                    self.rejected += 1;
                }
            }
            return Ok(());
        }
        let size = job.to_string().len();
        if self.retained + size + self.jobs.len() * 2 > BATCH_LIMIT {
            return Err(Failure("public_job_batch_result_limit"));
        }
        let index = self.jobs.len();
        self.seen.insert(key, (hash, Some(index)));
        self.retained += size;
        self.jobs.push(Some(job));
        Ok(())
    }
    fn cursor(&mut self, page: u32, more: bool) {
        self.next = if more && page < 100 {
            Some((page + 1).to_string())
        } else {
            None
        };
    }
}
fn schema() -> Failure {
    Failure("public_job_response_schema_invalid")
}
fn array<'a>(value: &'a Value, key: Option<&str>) -> Result<&'a Vec<Value>> {
    let value = key.map(|k| &value[k]).unwrap_or(value);
    value
        .as_array()
        .filter(|a| a.len() <= 100000)
        .ok_or_else(schema)
}
fn retry_at(raw: Option<&str>) -> DateTime<Utc> {
    let now = Utc::now();
    let maximum = DateTime::parse_from_rfc3339("9999-12-31T00:00:00Z")
        .expect("fixed date")
        .to_utc();
    if let Some(raw) = raw {
        if let Ok(seconds) = raw.parse::<u64>() {
            return i64::try_from(seconds)
                .ok()
                .and_then(chrono::Duration::try_seconds)
                .and_then(|delta| now.checked_add_signed(delta))
                .filter(|at| *at <= maximum)
                .unwrap_or(maximum)
                .max(now + chrono::Duration::seconds(1));
        }
        if let Ok(at) = DateTime::parse_from_rfc2822(raw) {
            return at
                .to_utc()
                .min(maximum)
                .max(now + chrono::Duration::seconds(1));
        }
    }
    now + chrono::Duration::seconds(60)
}
impl Client {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        let raw = values.get("RUST_PUBLIC_JOBS_FIXTURE_ORIGIN");
        if raw.is_some() && !fixture {
            return Err(Failure("public_job_fixture_origin_denied"));
        }
        let origin = raw
            .map(|s| Url::parse(s).map_err(|_| Failure("public_job_fixture_origin_denied")))
            .transpose()?;
        if origin.as_ref().is_some_and(|u| {
            u.scheme() != "http"
                || u.host_str() != Some("127.0.0.1")
                || u.port().is_none_or(|p| p < 1025)
                || u.path() != "/"
                || !u.username().is_empty()
                || u.password().is_some()
                || u.query().is_some()
                || u.fragment().is_some()
        }) {
            return Err(Failure("public_job_fixture_origin_denied"));
        }
        let http = Http::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("invalid_public_job_transport_settings"))?;
        Ok(Self {
            http,
            settings: Settings::from_values(values)?,
            fixture: origin,
        })
    }
    async fn get(&self, target: Target, work: &mut Work) -> Result<Value> {
        if work.attempts >= work.max_requests {
            return Err(Failure("public_job_batch_request_limit"));
        }
        let remaining = work
            .deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(15));
        if remaining.is_zero() {
            return Err(Failure("public_job_batch_timeout"));
        }
        let mut url = Url::parse(target.url()).map_err(|_| schema())?;
        let host = url.host_str().ok_or_else(schema)?.to_owned();
        let allowed = match work.source {
            Source::Greenhouse => host == "boards-api.greenhouse.io",
            Source::Lever => matches!(host.as_str(), "api.lever.co" | "api.eu.lever.co"),
            Source::Ashby => host == "api.ashbyhq.com",
            Source::Smartrecruiters => host == "api.smartrecruiters.com",
            Source::Remotive => host == "remotive.com",
            Source::Arbeitnow => host == "www.arbeitnow.com",
            Source::HackerNews => host == "hn.algolia.com",
        };
        if !allowed
            || url.scheme() != "https"
            || url.port().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err(Failure("public_job_target_denied"));
        }
        if let Some(origin) = &self.fixture {
            let path = format!("/fixtures/{}/{host}{}", work.source.name(), url.path());
            url = origin.clone();
            url.set_path(&path);
        }
        work.attempts += 1;
        let mut response = self
            .http
            .get(url)
            .query(target.query())
            .header("Accept", "application/json")
            .header("Cache-Control", "no-cache")
            .timeout(remaining)
            .send()
            .await
            .map_err(|_| {
                work.state = "outcome_unknown";
                Failure("public_job_transport_unconfirmed")
            })?;
        work.responses += 1;
        match response.status().as_u16() {
            200 => {}
            401 | 403 => {
                work.state = "authentication_required";
                return Err(Failure("public_job_provider_authentication_required"));
            }
            429 => {
                work.state = "rate_limited";
                work.cooldown = Some(retry_at(
                    response
                        .headers()
                        .get("retry-after")
                        .and_then(|v| v.to_str().ok()),
                ));
                if work.cooldown.is_some_and(|until| until.year() >= 9999) {
                    work.errors.insert("public_job_cooldown_requires_review");
                }
                return Err(Failure("public_job_provider_rate_limited"));
            }
            _ => return Err(Failure("public_job_http_unavailable")),
        }
        if response
            .content_length()
            .is_some_and(|n| n > RESPONSE_LIMIT as u64)
        {
            return Err(Failure("public_job_response_limit"));
        }
        let kind = response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .split(';')
            .next()
            .unwrap_or("")
            .trim()
            .to_ascii_lowercase();
        if kind != "application/json"
            && !(kind.starts_with("application/") && kind.ends_with("+json"))
        {
            return Err(Failure("public_job_json_required"));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| {
            work.state = "outcome_unknown";
            Failure("public_job_transport_unconfirmed")
        })? {
            if bytes.len() + chunk.len() > RESPONSE_LIMIT
                || work.bytes + chunk.len() > 32 * 1024 * 1024
            {
                return Err(Failure("public_job_response_limit"));
            }
            work.bytes += chunk.len();
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| Failure("public_job_json_invalid"))
    }
    async fn collect(&self, plan: &Snapshot, work: &mut Work) -> Result<()> {
        let source = plan.source();
        let page = plan.page();
        let limit = plan.limit();
        if matches!(source, Source::Greenhouse | Source::Lever | Source::Ashby) {
            let mut start = (page as usize - 1) * limit;
            let mut remaining = limit;
            for index in 0..plan.board_count() {
                let data = self.get(plan.board(index, start, remaining)?, work).await?;
                if source == Source::Ashby && data["apiVersion"] != "1" {
                    return Err(schema());
                }
                let all = array(
                    &data,
                    if source == Source::Lever {
                        None
                    } else {
                        Some("jobs")
                    },
                )?;
                let rows = all
                    .iter()
                    .filter(|r| source != Source::Ashby || r["isListed"] != false)
                    .collect::<Vec<_>>();
                if start >= rows.len() {
                    start -= rows.len();
                    continue;
                }
                let selected = rows
                    .iter()
                    .skip(start)
                    .take(remaining)
                    .copied()
                    .collect::<Vec<_>>();
                let (board, company) = plan.board_identity(index)?;
                for item in &selected {
                    let now = Utc::now();
                    let parsed = match source {
                        Source::Greenhouse => records::greenhouse(item, board, company, now),
                        Source::Lever => records::lever(item, board, company, plan.region(), now),
                        Source::Ashby => records::ashby(item, board, company, now),
                        _ => unreachable!(),
                    };
                    work.push(board, item, parsed)?;
                }
                work.cursor(
                    page,
                    rows.len() > start + selected.len() || index + 1 < plan.board_count(),
                );
                remaining -= selected.len();
                start = 0;
                if remaining == 0 {
                    break;
                }
            }
            return Ok(());
        }
        if source == Source::Smartrecruiters {
            let mut start = (page as usize - 1) * limit;
            let mut remaining = limit;
            let mut seen = BTreeSet::new();
            for index in 0..plan.board_count() {
                let data = self.get(plan.board(index, start, remaining)?, work).await?;
                let rows = array(&data, Some("content"))?;
                let total = data["totalFound"]
                    .as_u64()
                    .filter(|n| *n <= 10000000)
                    .ok_or_else(schema)? as usize;
                if data["offset"].as_u64() != Some(start as u64)
                    || data["limit"].as_u64() != Some(remaining as u64)
                    || rows.len() != remaining.min(total.saturating_sub(start))
                {
                    return Err(schema());
                }
                if start >= total {
                    start -= total;
                    continue;
                }
                let (board, company) = plan.board_identity(index)?;
                for row in rows {
                    let Some(id) = row["id"].as_str().filter(|s| {
                        !s.is_empty()
                            && s.len() <= 100
                            && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
                    }) else {
                        work.rejected += 1;
                        work.errors.insert("public_job_record_invalid");
                        continue;
                    };
                    if !seen.insert((board.to_owned(), id.to_owned())) {
                        work.rejected += 1;
                        work.duplicates += 1;
                        work.errors.insert("public_job_inconsistent_duplicate");
                        if let Some((_, entry)) = work.seen.get_mut(&format!("{board}\0{id}"))
                            && let Some(index) = entry.take()
                            && let Some(prior) = work.jobs[index].take()
                        {
                            work.retained = work.retained.saturating_sub(prior.to_string().len());
                            work.rejected += 1;
                        }
                        continue;
                    }
                    let detail = self.get(plan.detail(index, id)?, work).await?;
                    let parsed = records::smartrecruiters(&detail, board, company, id, Utc::now());
                    work.push(board, &detail, parsed)?;
                }
                work.cursor(
                    page,
                    total > start + rows.len() || index + 1 < plan.board_count(),
                );
                remaining -= rows.len();
                start = 0;
                if remaining == 0 {
                    break;
                }
            }
            return Ok(());
        }
        let data = self.get(plan.root()?, work).await?;
        match source {
            Source::Remotive => {
                let rows = array(&data, Some("jobs"))?;
                if rows.len() > 1000 {
                    return Err(schema());
                }
                for item in rows.iter().skip((page as usize - 1) * limit).take(limit) {
                    work.push("", item, records::remotive(item, Utc::now()))?;
                }
            }
            Source::Arbeitnow => {
                let links = match data.get("links") {
                    None | Some(Value::Null) => json!({}),
                    Some(v) if v.is_object() => v.clone(),
                    _ => return Err(schema()),
                };
                work.cursor(
                    page,
                    links
                        .get("next")
                        .is_some_and(|v| !v.is_null() && v != false && v != ""),
                );
                for item in array(&data, Some("data"))?.iter().take(limit) {
                    work.push("", item, records::arbeitnow(item, page, Utc::now()))?;
                }
            }
            Source::HackerNews => {
                let stories = array(&data, Some("hits"))?;
                if stories.len() > 10
                    || stories
                        .iter()
                        .any(|s| !s.is_object() || s.get("title").is_some_and(|v| !v.is_string()))
                {
                    return Err(schema());
                }
                let mut selected = None;
                for story in stories {
                    if let Some(title) = story["title"].as_str().filter(|s| s.len() <= 2000) {
                        static HIRING: std::sync::LazyLock<crate::legacy_regex::Regex> =
                            std::sync::LazyLock::new(|| {
                                crate::legacy_regex::Regex::new(r"who is hiring\?", true)
                            });
                        if HIRING.is_match(title).map_err(|_| schema())? {
                            selected = Some(story);
                            break;
                        }
                    }
                }
                let Some(story) = selected else { return Ok(()) };
                let id = story["objectID"].as_str().ok_or_else(schema)?;
                let title = story["title"].as_str().ok_or_else(schema)?;
                let comments = self.get(plan.comments(id)?, work).await?;
                let pages = comments
                    .get("nbPages")
                    .map(|v| v.as_u64().filter(|n| *n <= 100000).ok_or_else(schema))
                    .transpose()?
                    .unwrap_or(1);
                work.cursor(page, pages > page as u64);
                for item in array(&comments, Some("hits"))?.iter().take(limit) {
                    work.push("", item, records::hacker_news(item, id, title, Utc::now()))?;
                }
            }
            _ => return Err(schema()),
        }
        Ok(())
    }
    pub(super) async fn execute(&self, grant: Grant) -> Outcome {
        let plan = &grant.snapshot;
        let now = Utc::now();
        let mut work = Work {
            source: plan.source(),
            deadline: Instant::now() + Duration::from_secs(75),
            max_requests: match plan.source() {
                Source::Greenhouse | Source::Lever | Source::Ashby => plan.board_count(),
                Source::Smartrecruiters => plan.board_count() + plan.limit(),
                Source::HackerNews => 2,
                _ => 1,
            },
            attempts: 0,
            responses: 0,
            bytes: 0,
            jobs: Vec::new(),
            retained: 0,
            seen: BTreeMap::new(),
            errors: BTreeSet::new(),
            rejected: 0,
            duplicates: 0,
            next: None,
            state: "upstream_error",
            cooldown: None,
        };
        let expected = Snapshot::build(&self.settings, plan.source(), plan.query().clone());
        let allowed = expected
            .as_ref()
            .is_ok_and(|p| p.context() == plan.context());
        let complete = if now >= grant.expires || !allowed {
            work.state = "not_dispatched";
            work.errors.insert(if allowed {
                "public_job_original_grant_expired"
            } else {
                "public_job_original_grant_changed"
            });
            false
        } else {
            work.deadline = Instant::now()
                + (grant.expires - now)
                    .to_std()
                    .unwrap_or_default()
                    .min(Duration::from_secs(75));
            match tokio::time::timeout_at(work.deadline, self.collect(plan, &mut work)).await {
                Ok(Ok(())) if Instant::now() < work.deadline => true,
                Ok(Ok(())) => {
                    work.state = "outcome_unknown";
                    work.errors.insert("public_job_batch_timeout");
                    false
                }
                Ok(Err(e)) => {
                    work.errors.insert(e.0);
                    false
                }
                Err(_) => {
                    work.state = "outcome_unknown";
                    work.errors.insert("public_job_batch_timeout");
                    false
                }
            }
        };
        if !complete {
            work.next = None;
        }
        let jobs = work.jobs.into_iter().flatten().collect::<Vec<_>>();
        let status = if complete {
            if work.rejected > 0 {
                if jobs.is_empty() {
                    "upstream_error"
                } else {
                    "partial"
                }
            } else if jobs.is_empty() {
                "no_results"
            } else {
                "success"
            }
        } else if !jobs.is_empty() {
            "partial"
        } else {
            work.state
        };
        let finding = json!({"source":plan.source().name(),"status":status,"transport_state":if complete{"completed"}else{work.state},"batch_complete":complete,"jobs":jobs,"errors":work.errors,"rejected_count":work.rejected,"duplicate_count":work.duplicates,"next_cursor":work.next,"provider_http_attempts":work.attempts,"provider_responses_observed":work.responses,"decoded_bytes":work.bytes,"observed_at":Utc::now().to_rfc3339(),"application_dispatch":false,"live_verified":false});
        Outcome {
            request: grant.id,
            invocation: grant.invocation,
            configuration: plan.context().to_owned(),
            finding,
            cooldown: work.cooldown,
        }
    }
}
