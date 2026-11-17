//! Transport authorization and closed route/query classification.
use super::*;

pub(super) fn single<'a>(headers: &'a HeaderMap, key: &str) -> Option<&'a str> {
    let mut entries = headers.get_all(key).iter();
    let value = entries.next()?.to_str().ok()?;
    if entries.next().is_some() {
        None
    } else {
        Some(value)
    }
}
pub(super) fn saved_match_route(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/jobs/")
        .and_then(|tail| tail.strip_suffix("/match"))
        .filter(|id| !id.is_empty() && !id.contains('/'))
}
pub(super) fn profile_route(path: &str) -> bool {
    path == "/api/v1/profile"
        || saved_match_route(path).is_some()
        || path == "/api/v1/local-agent/profile-confirmation"
        || path == crate::conversation::preferences::PATH
        || path == crate::platform_policy::PATH
        || crate::platform_sessions::route(path).is_some()
        || resource_inspection(path)
        || candidate_resource_route(path)
        || draft_route(path)
        || missing_route(path)
        || path == "/api/v1/application-answers/generate"
        || path == "/api/v1/application-answers/reuse-approvals"
        || resume_route(path).is_some()
        || crate::notifications::route(path).is_some()
        || path == crate::notification_preferences::PATH
        || crate::job_catalog::route(path).is_some()
        || crate::contacts::route(path).is_some()
        || crate::companies::route(path).is_some()
        || crate::startup_catalog::detail::route(path).is_some()
        || crate::startup_catalog::owner::route(path).is_some()
        || crate::job_sources::owner::route(path).is_some()
        || crate::people_research::owner::route(path).is_some()
        || crate::apify_metadata::owner::route(path).is_some()
        || crate::startup_catalog::search::route(path).is_some()
        || crate::startup_catalog::shortlist::route(path).is_some()
        || crate::outreach::history::route(path).is_some()
        || crate::outreach::drafts::route(path).is_some()
        || crate::outreach::controller::route(path).is_some()
        || crate::contacts::enrichment::route(path).is_some()
        || crate::contacts::enrichment::io_route(path).is_some()
        || crate::packet_service::route(path).is_some()
        || crate::packet_generation::route(path).is_some()
        || crate::resume_review::route(path).is_some()
        || crate::browser_profiles::route(path).is_some()
        || crate::execution::route(path).is_some()
        || crate::gmail_history::route(path).is_some()
        || crate::gmail_legacy::route(path).is_some()
        || crate::gmail_legacy::io_route(path).is_some()
        || crate::gmail_workspace::route(path).is_some()
        || crate::gmail_workspace::io_route(path).is_some()
        || crate::gmail_accounts::route(path).is_some()
        || crate::gmail_accounts::io_route(path).is_some()
}
pub(super) fn resume_route(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/dashboard/resumes")?;
    if tail.is_empty() {
        return Some(("", ""));
    }
    let tail = tail.strip_prefix('/')?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    (!id.is_empty() && matches!(action, "" | "confirm")).then_some((id, action))
}
pub(super) fn resume_label(query: Option<&str>) -> Result<String> {
    let Some(query) = query else {
        return Ok("Resume".into());
    };
    let raw = query
        .strip_prefix("label=")
        .filter(|s| !s.contains('&') && s.len() <= 2400)
        .ok_or(Failure("invalid_resume_label"))?;
    let raw = raw.replace('+', " ");
    let label = percent_encoding::percent_decode_str(&raw)
        .decode_utf8()
        .map_err(|_| Failure("invalid_resume_label"))?
        .into_owned();
    if label.is_empty() || label.chars().count() > 200 {
        return Err(Failure("invalid_resume_label"));
    }
    Ok(label)
}
pub(super) fn missing_item(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/application-answers/missing/")?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    (!id.is_empty() && matches!(action, "" | "approve" | "history")).then_some((id, action))
}
pub(super) fn missing_route(path: &str) -> bool {
    path == "/api/v1/application-answers/missing" || missing_item(path).is_some()
}
pub(super) fn paginated(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/candidate/resources"
            | "/api/v1/candidate/evidence"
            | "/api/v1/application-answers/drafts"
            | "/api/v1/application-answers/missing"
            | crate::notifications::INBOX
    ) || missing_item(path).is_some_and(|(_, action)| action == "history")
}
pub(super) fn draft_id(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/application-answers/drafts/")
        .filter(|s| !s.is_empty() && !s.contains('/'))
}
pub(super) fn draft_route(path: &str) -> bool {
    path == "/api/v1/application-answers/drafts"
        || draft_id(path).is_some()
        || draft_action(path).is_some()
}
pub(super) fn draft_action(path: &str) -> Option<(&str, &str)> {
    let tail = path.strip_prefix("/api/v1/application-answers/drafts/")?;
    let (id, action) = tail.split_once('/')?;
    (!id.is_empty()
        && matches!(
            action,
            "approve-reuse" | "revoke-reuse" | "opportunity-evidence"
        ))
    .then_some((id, action))
}
pub(super) fn candidate_resource_route(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/candidate/resources"
            | "/api/v1/candidate/evidence"
            | "/api/v1/candidate/resources/resolve"
    ) || evidence_id(path).is_some()
}
pub(super) fn evidence_id(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/candidate/evidence/")
        .filter(|id| !id.is_empty() && !id.contains('/'))
}
pub(super) fn resource_page(path: &str, method: &str, query: Option<&str>) -> Result<(i64, i64)> {
    let mut page = (0, 25);
    let invalid = Failure(if path == crate::notifications::INBOX {
        "invalid_notification_page"
    } else {
        "invalid_resource_page"
    });
    let Some(query) = query else {
        return Ok(page);
    };
    if !paginated(path) || method != "GET" || query.len() > 256 {
        return Err(Failure("query_parameters_not_supported"));
    }
    let mut seen = std::collections::HashSet::new();
    for (key, value) in reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
        .map_err(|_| invalid)?
        .query_pairs()
    {
        if !seen.insert(key.to_string()) {
            return Err(invalid);
        }
        match key.as_ref() {
            "offset" => {
                page.0 = crate::profile_contract::pagination_integer(json!(value), 0, 100000)
                    .map_err(|_| invalid)?
            }
            "limit" => {
                if path == crate::notifications::INBOX {
                    return Err(invalid);
                }
                page.1 = crate::profile_contract::pagination_integer(json!(value), 1, 100)
                    .map_err(|_| invalid)?
            }
            _ => return Err(invalid),
        }
    }
    Ok(page)
}
pub(super) fn resource_inspection(path: &str) -> bool {
    matches!(
        path,
        "/api/v1/rust-agent/profile-readiness" | "/api/v1/rust-agent/resume-selection"
    )
}
pub(super) fn selected_resource(
    path: &str,
    method: &str,
    query: Option<&str>,
) -> Result<Option<Uuid>> {
    let Some(query) = query else {
        return Ok(None);
    };
    if path == "/api/v1/dashboard/resumes" && method == "POST" {
        resume_label(Some(query))?;
        return Ok(None);
    }
    if paginated(path) && method == "GET" {
        return Ok(None);
    }
    if crate::job_catalog::route(path).is_some()
        || crate::gmail_accounts::route(path).is_some()
        || crate::execution::route(path).is_some()
        || path == crate::notification_preferences::PATH
        || crate::packet_service::route(path).is_some()
        || crate::packet_generation::route(path).is_some()
        || (saved_match_route(path).is_some() && method == "GET")
    {
        return Ok(None);
    }
    if path != "/api/v1/rust-agent/resume-selection" || method != "GET" {
        return Err(Failure("query_parameters_not_supported"));
    }
    let raw = query
        .strip_prefix("selected_id=")
        .filter(|s| !s.contains('&') && s.len() <= 100)
        .ok_or(Failure("invalid_resource_selection"))?;
    raw.parse()
        .map(Some)
        .map_err(|_| Failure("invalid_resource_selection"))
}
pub(super) fn authorize(request: &Request, config: &Configuration) -> Result<()> {
    let private_peer = request
        .extensions()
        .get::<ConnectInfo<crate::local_socket::OwnerPeer>>()
        .is_some_and(|p| p.0.accepted());
    if !private_peer
        && !request
            .extensions()
            .get::<ConnectInfo<SocketAddr>>()
            .is_some_and(|peer| peer.0.ip().is_loopback())
    {
        return Err(Failure("owner_peer_denied"));
    }
    let headers = request.headers();
    let host = single(headers, "host").ok_or(Failure("owner_host_denied"))?;
    let authority = host
        .parse::<axum::http::uri::Authority>()
        .map_err(|_| Failure("owner_host_denied"))?;
    if host.contains(['@', '/', '?', '#'])
        || !(private_peer
            && authority.host() == "127.0.0.1"
            && authority.port_u16() == Some(config.listen.port()))
            && !config.hosts.iter().any(|h| {
                h.eq_ignore_ascii_case(host)
                    || (!h.contains(':') && h.eq_ignore_ascii_case(authority.host()))
            })
    {
        return Err(Failure("owner_host_denied"));
    }
    let native = request.uri().path() == crate::browser_profiles::NATIVE;
    let extension = single(headers, "x-agent-client");
    if native && !config.browser_profiles.permits(extension) {
        return Err(Failure("extension_identity_not_authorized"));
    }
    if headers.contains_key("origin")
        && single(headers, "origin").is_none_or(|value| {
            !config.origins.iter().any(|s| s == value)
                && !(native
                    && config
                        .browser_profiles
                        .extension
                        .as_ref()
                        .is_some_and(|id| value == format!("chrome-extension://{id}")))
        })
    {
        return Err(Failure("owner_origin_denied"));
    }
    if request.method() == axum::http::Method::GET && request.uri().path() == "/health" {
        return Ok(());
    }
    if headers.contains_key("x-agent-client") && !native {
        return Err(Failure("owner_client_required"));
    }
    if config.require_tls
        && !private_peer
        && !(config.trust_proxy && single(headers, "x-forwarded-proto") == Some("https"))
    {
        return Err(Failure("owner_api_tls_required"));
    }
    if crate::http_policy::unauthenticated_callback(request.uri().path(), request.method().as_str())
    {
        // Public browser callback has its own one-use state, cookie, PKCE and exact URI checks.
        return Ok(());
    }
    let token = single(headers, "authorization")
        .and_then(|s| {
            if profile_route(request.uri().path()) {
                s.split_once(' ')
                    .filter(|(scheme, _)| scheme.eq_ignore_ascii_case("bearer"))
                    .map(|(_, token)| token)
            } else {
                s.strip_prefix("Bearer ")
            }
        })
        .ok_or(Failure("owner_authentication_required"))?;
    if !bool::from(token.as_bytes().ct_eq(config.token.as_bytes())) {
        return Err(Failure("owner_authentication_required"));
    }
    Ok(())
}
