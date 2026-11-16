//! Fixed-role authorization uses the same bounded transient permit; no owner lock across IO.
use super::*;
use crate::gmail_workspace::{self, IoRoute, Slot, account};
fn error(failure: Failure, callback: bool) -> Response {
    if callback {
        return reply(StatusCode::BAD_REQUEST, json!({"detail":failure.0}));
    }
    if failure.0 == "invalid_gmail_workspace_contract" {
        return reply(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({"detail":failure.0}),
        );
    }
    if failure.0.contains("database_error")
        || failure.0.contains("write_ack_failed")
        || failure.0.contains("commit_outcome_unknown")
        || failure.0.starts_with("invalid_gmail_workspace_saved")
    {
        return reply(StatusCode::SERVICE_UNAVAILABLE, json!({"detail":failure.0}));
    }
    reply(StatusCode::CONFLICT, json!({"detail":failure.0}))
}
fn cookie(response: &mut Response, value: &str, ttl: i64, secure: bool) {
    if let Ok(value) = axum::http::HeaderValue::from_str(&format!(
        "gmail_oauth_browser={value}; HttpOnly; Max-Age={ttl}; Path={}; SameSite=Lax{}",
        crate::mailboxes::routes::CALLBACK,
        if secure { "; Secure" } else { "" }
    )) {
        response.headers_mut().append("set-cookie", value);
    }
}
async fn connection(api: &Api) -> Result<PgConnection> {
    let mut c = api.config.connect(false).await?;
    if let Err(error) = readiness(&mut c, &api.config).await {
        recovery::close(c).await;
        return Err(error);
    }
    Ok(c)
}
pub(super) async fn dispatch(
    api: &Api,
    route: IoRoute,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if method != "POST" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_workspace_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("POST"));
        return response;
    }
    if query.is_some_and(|s| !s.is_empty()) {
        return error(Failure("invalid_gmail_workspace_contract"), false);
    }
    let input = match route {
        IoRoute::Connect(_) => match serde_json::from_slice(body)
            .map_err(|_| Failure("invalid_gmail_workspace_contract"))
            .and_then(|v| {
                gmail_workspace::contract::normalize(gmail_workspace::contract::Kind::Consent, v)
            }) {
            Ok(input) => input,
            Err(e) => return error(e, false),
        },
        IoRoute::Disconnect => {
            if !body.is_empty()
                && !serde_json::from_slice::<Value>(body)
                    .is_ok_and(|v| v.as_object().is_some_and(|o| o.is_empty()))
            {
                return error(Failure("invalid_gmail_workspace_contract"), false);
            }
            Value::Null
        }
    };
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match connection(api).await {
        Ok(c) => c,
        Err(e) => return error(e, false),
    };
    let browser = crate::mailboxes::browser_nonce();
    let settings = &api.config.gmail_accounts;
    let result = tokio::time::timeout(Duration::from_secs(65), async {
        match route {
            IoRoute::Disconnect => account::disconnect(&mut c).await,
            IoRoute::Connect(slot) => {
                let provider = api.config.mailboxes.provider()?;
                match slot {
                    Slot::Outreach => {
                        account::Service { settings, provider }
                            .start(&mut c, input, &browser)
                            .await
                    }
                    _ => {
                        gmail_workspace::start_read(
                            &mut c, slot, input, &browser, settings, provider,
                        )
                        .await
                    }
                }
            }
        }
    })
    .await
    .unwrap_or(Err(Failure("gmail_workspace_operation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => {
            let mut response = reply(StatusCode::OK, value);
            if matches!(route, IoRoute::Connect(_)) {
                let secure = api
                    .config
                    .mailboxes
                    .provider()
                    .is_ok_and(|p| p.redirect_uri().starts_with("https:"));
                cookie(&mut response, &browser, settings.ttl, secure);
            }
            response
        }
        Err(e) => error(e, false),
    }
}
pub(super) fn recognizes_callback(query: Option<&str>) -> bool {
    query
        .filter(|s| s.len() <= 16000)
        .and_then(|s| reqwest::Url::parse(&format!("http://127.0.0.1/?{s}")).ok())
        .is_some_and(|u| {
            u.query_pairs()
                .any(|(k, v)| k == "state" && v.starts_with("draft."))
        })
}
pub(super) async fn callback(api: &Api, request: Request) -> Response {
    let decoded =
        match crate::gmail_accounts::oauth::callback_prefix(request.uri().query(), "draft.") {
            Ok(v) => v,
            Err(e) => return error(e, true),
        };
    let browser = match crate::gmail_accounts::oauth::browser_cookie(request.headers()) {
        Ok(v) => v,
        Err(e) => return error(e, true),
    };
    let host = match single(request.headers(), "host") {
        Some(host) => host,
        None => return error(Failure("invalid_oauth_state_or_redirect"), true),
    };
    let scheme = if api.config.trust_proxy
        && single(request.headers(), "x-forwarded-proto") == Some("https")
    {
        "https"
    } else {
        "http"
    };
    let uri = format!("{scheme}://{host}{}", crate::mailboxes::routes::CALLBACK);
    let provider = match api.config.mailboxes.provider() {
        Ok(p) => p,
        Err(e) => return error(e, true),
    };
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match connection(api).await {
        Ok(c) => c,
        Err(e) => return error(e, true),
    };
    let service = account::Service {
        settings: &api.config.gmail_accounts,
        provider,
    };
    let result = tokio::time::timeout(
        Duration::from_secs(65),
        service.callback(
            &mut c,
            &decoded.state,
            &browser,
            &uri,
            decoded.code.as_deref(),
            decoded.error.as_deref(),
        ),
    )
    .await
    .unwrap_or(Err(Failure("gmail_workspace_operation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => {
            let mut response = reply(
                StatusCode::OK,
                json!({"status":"connected","connection":value}),
            );
            cookie(
                &mut response,
                "",
                0,
                provider.redirect_uri().starts_with("https:"),
            );
            response
        }
        Err(e) => error(e, true),
    }
}
