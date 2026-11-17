//! Closed public GET targets. A pure request plan is never a remote dispatch grant.
use super::contract;
use crate::{Failure, Result, source_registry::Settings};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    Greenhouse,
    Lever,
    Ashby,
    Smartrecruiters,
    Remotive,
    Arbeitnow,
    HackerNews,
}
impl Source {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "greenhouse" => Ok(Self::Greenhouse),
            "lever" => Ok(Self::Lever),
            "ashby" => Ok(Self::Ashby),
            "smartrecruiters" => Ok(Self::Smartrecruiters),
            "remotive" => Ok(Self::Remotive),
            "arbeitnow" => Ok(Self::Arbeitnow),
            "hacker_news" => Ok(Self::HackerNews),
            _ => Err(Failure("public_job_source_unknown")),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Greenhouse => "greenhouse",
            Self::Lever => "lever",
            Self::Ashby => "ashby",
            Self::Smartrecruiters => "smartrecruiters",
            Self::Remotive => "remotive",
            Self::Arbeitnow => "arbeitnow",
            Self::HackerNews => "hacker_news",
        }
    }
    pub fn interval_seconds(self) -> i64 {
        if self == Self::Remotive { 21600 } else { 60 }
    }
    pub fn needs_boards(self) -> bool {
        matches!(
            self,
            Self::Greenhouse | Self::Lever | Self::Ashby | Self::Smartrecruiters
        )
    }
}
/// Transport target constructors are closed; callers cannot supply URLs, headers or HTTP methods.
pub struct Target {
    url: String,
    query: Vec<(String, String)>,
}
impl Target {
    fn fixed(url: String, query: Vec<(&str, String)>) -> Self {
        Self {
            url,
            query: query.into_iter().map(|(k, v)| (k.into(), v)).collect(),
        }
    }
    pub fn url(&self) -> &str {
        &self.url
    }
    pub fn query(&self) -> &[(String, String)] {
        &self.query
    }
}
pub struct Snapshot {
    source: Source,
    query: Value,
    boards: Vec<(String, String)>,
    region: String,
    context: String,
}
fn invalid() -> Failure {
    Failure("invalid_public_job_request_plan")
}
fn id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 100
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-')
}
impl Snapshot {
    pub fn build(settings: &Settings, source: Source, query: Value) -> Result<Self> {
        if query.to_string().len() > 16384 {
            return Err(invalid());
        }
        let query = contract::query(query)?;
        let boards = settings
            .public_boards(source.name())
            .and_then(Value::as_object)
            .map(|o| {
                o.iter()
                    .map(|(k, v)| {
                        v.as_str()
                            .map(|v| (k.clone(), v.to_owned()))
                            .ok_or_else(invalid)
                    })
                    .collect::<Result<Vec<_>>>()
            })
            .transpose()?
            .unwrap_or_default();
        if source.needs_boards() && boards.is_empty() {
            return Err(Failure("public_job_boards_not_configured"));
        }
        if source == Source::Remotive
            && query["page"].as_u64().ok_or_else(invalid)?
                * query["limit"].as_u64().ok_or_else(invalid)?
                > 1000
        {
            return Err(Failure("public_job_remotive_page_limit"));
        }
        let region = if source == Source::Lever {
            settings.lever_region()
        } else {
            "global"
        }
        .to_owned();
        let context = crate::python_json::digest(
            &json!({"schema":1,"source":source,"boards":boards,"region":region,"board_order":"native_sorted_ids","normalization":"selected_provenance_v1"}),
        );
        Ok(Self {
            source,
            query,
            boards,
            region,
            context,
        })
    }
    pub fn source(&self) -> Source {
        self.source
    }
    pub fn query(&self) -> &Value {
        &self.query
    }
    pub fn context(&self) -> &str {
        &self.context
    }
    pub fn page(&self) -> u32 {
        self.query["page"].as_u64().expect("validated page") as u32
    }
    pub fn limit(&self) -> usize {
        self.query["limit"].as_u64().expect("validated limit") as usize
    }
    pub fn board_count(&self) -> usize {
        self.boards.len()
    }
    pub(crate) fn board_identity(&self, index: usize) -> Result<(&str, &str)> {
        self.boards
            .get(index)
            .map(|(id, company)| (id.as_str(), company.as_str()))
            .ok_or_else(invalid)
    }
    pub(crate) fn region(&self) -> &str {
        &self.region
    }
    pub fn root(&self) -> Result<Target> {
        let page = self.page();
        let limit = self.limit();
        match self.source {
            Source::Remotive => {
                let words = self.query["keywords"]
                    .as_array()
                    .ok_or_else(invalid)?
                    .iter()
                    .map(|v| v.as_str().ok_or_else(invalid))
                    .collect::<Result<Vec<_>>>()?
                    .join(" ");
                Ok(Target::fixed(
                    "https://remotive.com/api/remote-jobs".into(),
                    vec![
                        ("category", "software-dev".into()),
                        ("limit", (page as usize * limit).to_string()),
                        ("search", words),
                    ],
                ))
            }
            Source::Arbeitnow => Ok(Target::fixed(
                "https://www.arbeitnow.com/api/job-board-api".into(),
                vec![("page", page.to_string())],
            )),
            Source::HackerNews => Ok(Target::fixed(
                "https://hn.algolia.com/api/v1/search_by_date".into(),
                vec![
                    ("tags", "story,author_whoishiring".into()),
                    ("hitsPerPage", "10".into()),
                ],
            )),
            _ => Err(invalid()),
        }
    }
    pub fn board(&self, index: usize, offset: usize, remaining: usize) -> Result<Target> {
        if offset > (self.page() as usize - 1) * self.limit()
            || remaining == 0
            || remaining > self.limit()
        {
            return Err(invalid());
        }
        let (board, _) = self.board_identity(index)?;
        match self.source {
            Source::Greenhouse => Ok(Target::fixed(
                format!("https://boards-api.greenhouse.io/v1/boards/{board}/jobs"),
                vec![("content", "true".into())],
            )),
            Source::Lever => Ok(Target::fixed(
                format!(
                    "https://{}/v0/postings/{board}",
                    if self.region == "eu" {
                        "api.eu.lever.co"
                    } else {
                        "api.lever.co"
                    }
                ),
                vec![("mode", "json".into())],
            )),
            Source::Ashby => Ok(Target::fixed(
                format!("https://api.ashbyhq.com/posting-api/job-board/{board}"),
                vec![("includeCompensation", "true".into())],
            )),
            Source::Smartrecruiters => Ok(Target::fixed(
                format!("https://api.smartrecruiters.com/v1/companies/{board}/postings"),
                vec![
                    ("offset", offset.to_string()),
                    ("limit", remaining.to_string()),
                ],
            )),
            _ => Err(invalid()),
        }
    }
    pub fn detail(&self, index: usize, identifier: &str) -> Result<Target> {
        if self.source != Source::Smartrecruiters || !id(identifier) {
            return Err(invalid());
        }
        let (board, _) = self.board_identity(index)?;
        Ok(Target::fixed(
            format!("https://api.smartrecruiters.com/v1/companies/{board}/postings/{identifier}"),
            vec![],
        ))
    }
    pub fn comments(&self, story: &str) -> Result<Target> {
        if self.source != Source::HackerNews
            || story.is_empty()
            || story.len() > 100
            || !story.bytes().all(|b| b.is_ascii_digit())
        {
            return Err(invalid());
        }
        Ok(Target::fixed(
            "https://hn.algolia.com/api/v1/search".into(),
            vec![
                ("tags", format!("comment,story_{story}")),
                ("hitsPerPage", self.limit().to_string()),
                ("page", (self.page() - 1).to_string()),
                ("numericFilters", format!("parent_id={story}")),
            ],
        ))
    }
}
