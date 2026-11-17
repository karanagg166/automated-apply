//! Closed owner paths; UUID in the native path prevents legacy unkeyed POST replay.
use uuid::Uuid;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Route {
    Status,
    Request(Uuid),
    Legacy,
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/rust-agent/research/people/status" => Some(Route::Status),
        "/api/v1/discovery/people/search" => Some(Route::Legacy),
        _ => path
            .strip_prefix("/api/v1/rust-agent/research/people/requests/")
            .and_then(|s| s.parse().ok())
            .map(Route::Request),
    }
}
impl Route {
    pub fn accepts(self, method: &str) -> bool {
        match self {
            Self::Status => method == "GET",
            Self::Legacy => method == "POST",
            Self::Request(_) => matches!(method, "GET" | "PUT"),
        }
    }
    pub fn allow(self) -> &'static str {
        match self {
            Self::Status => "GET",
            Self::Legacy => "POST",
            Self::Request(_) => "GET, PUT",
        }
    }
}
