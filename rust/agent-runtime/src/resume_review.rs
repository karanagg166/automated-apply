//! Existing resume source/review controls. Drive downloading remains explicitly deferred.
mod contract;
mod review;
mod state;
use crate::{Failure, Result};
pub use contract::{
    Approval, SourceInput, approval_request, canonical_source, differences, source_request,
};
pub use review::{approve, changes};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
pub use state::{Settings, save_source, status};
use uuid::Uuid;
pub const ROOT: &str = "/api/v1/dashboard/resume-sync";
#[derive(Clone, Copy)]
pub enum Route<'a> {
    Status,
    Source,
    Sync,
    Review(&'a str),
    Approve(&'a str),
}
impl Route<'_> {
    pub fn method(self) -> &'static str {
        match self {
            Self::Status | Self::Review(_) => "GET",
            Self::Source => "PUT",
            Self::Sync | Self::Approve(_) => "POST",
        }
    }
}
pub fn route(path: &str) -> Option<Route<'_>> {
    if path == ROOT {
        return Some(Route::Status);
    }
    let tail = path.strip_prefix(ROOT)?.strip_prefix('/')?;
    match tail {
        "source" => Some(Route::Source),
        "sync" => Some(Route::Sync),
        _ => {
            let tail = tail.strip_prefix("versions/")?;
            let (id, action) = tail.split_once('/')?;
            if id.is_empty() || id.contains('/') {
                return None;
            }
            match action {
                "review" => Some(Route::Review(id)),
                "approve" => Some(Route::Approve(id)),
                _ => None,
            }
        }
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("resume_review_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_resume_review_request")
}

pub async fn dispatch(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    body: &[u8],
    settings: &Settings,
    crypto: &crate::private_resume::Settings,
    live: bool,
) -> Result<Value> {
    let expected = route.method();
    if method != expected {
        return Err(Failure("resume_review_method_not_allowed"));
    }
    let parse = || serde_json::from_slice::<Value>(body).map_err(|_| invalid());
    match route {
        Route::Status => status(c, settings).await,
        Route::Source => save_source(c, source_request(parse()?)?, settings).await,
        Route::Sync => {
            let input = parse()?;
            if input
                .as_object()
                .is_none_or(|v| v.keys().any(|key| key != "expected_generation"))
                || crate::profile_contract::pagination_integer(
                    input["expected_generation"].clone(),
                    1,
                    i32::MAX as i64 - 1,
                )
                .is_err()
            {
                return Err(invalid());
            }
            Err(Failure("drive_oauth_deferred_use_manual_pdf_upload"))
        }
        Route::Review(id) => {
            changes(
                c,
                id.parse().map_err(|_| Failure("resume_review_not_found"))?,
                crypto,
            )
            .await
        }
        Route::Approve(id) => {
            approve(
                c,
                id.parse().map_err(|_| Failure("resume_review_not_found"))?,
                approval_request(parse()?)?,
                settings,
                crypto,
                live,
            )
            .await
        }
    }
}
