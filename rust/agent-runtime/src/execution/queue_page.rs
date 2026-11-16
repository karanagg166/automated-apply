//! Legacy scalar read filters. Unknown read keys are ignored; duplicate scalar uses the last value.
use crate::{Failure, Result};
use serde_json::json;
pub struct Page {
    pub platform: Option<String>,
    pub stage: Option<String>,
    pub search: Option<String>,
    pub location: Option<String>,
    pub minimum_score: Option<i64>,
    pub limit: i64,
    pub offset: i64,
}
impl Default for Page {
    fn default() -> Self {
        Self {
            platform: None,
            stage: None,
            search: None,
            location: None,
            minimum_score: None,
            limit: 100,
            offset: 0,
        }
    }
}
fn invalid() -> Failure {
    Failure("invalid_execution_page")
}
impl Page {
    pub fn parse(query: Option<&str>) -> Result<Self> {
        let mut values = std::collections::BTreeMap::new();
        if let Some(raw) = query {
            if raw.len() > 4096 {
                return Err(invalid());
            }
            let url =
                reqwest::Url::parse(&format!("http://127.0.0.1/?{raw}")).map_err(|_| invalid())?;
            for (k, v) in url.query_pairs() {
                values.insert(k.into_owned(), v.into_owned());
            }
        }
        let integer = |key: &str, minimum: i64, maximum: i64| {
            values
                .get(key)
                .map(|v| {
                    crate::profile_contract::pagination_integer(json!(v), minimum, maximum)
                        .map_err(|_| invalid())
                })
                .transpose()
        };
        let label = |key: &str| -> Result<Option<String>> {
            values
                .get(key)
                .map(|v| {
                    if v.chars().count() <= 200 {
                        Ok(v.clone())
                    } else {
                        Err(invalid())
                    }
                })
                .transpose()
        };
        let platform = values.get("platform").cloned();
        if platform.as_deref().is_some_and(|s| s != "naukri") {
            return Err(invalid());
        }
        const STAGES: &[&str] = &[
            "DISCOVERED",
            "MATCHED",
            "ELIGIBLE",
            "PREPARING",
            "READY_TO_APPLY",
            "APPLYING",
            "QUESTIONS",
            "RESUME_ATTACHMENT",
            "VERIFYING",
            "SUBMITTED_RECORDED",
            "NEEDS_INPUT",
            "PAUSED",
            "BLOCKED_PLATFORM",
            "FAILED_RETRYABLE",
            "FAILED_FINAL",
            "SUBMISSION_UNKNOWN",
            "SUBMITTED_CONFIRMED",
            "SKIPPED",
        ];
        let stage = values.get("stage").cloned();
        if stage.as_deref().is_some_and(|s| !STAGES.contains(&s)) {
            return Err(invalid());
        }
        Ok(Self {
            platform,
            stage,
            search: label("search")?,
            location: label("location")?,
            minimum_score: integer("minimum_score", 0, 100)?,
            limit: integer("limit", 1, 200)?.unwrap_or(100),
            offset: integer("offset", 0, i64::MAX)?.unwrap_or(0),
        })
    }
}
