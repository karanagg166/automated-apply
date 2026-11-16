//! Original primary account routes/callback on the shared transient IO permit.
use super::*;
use crate::gmail_legacy::{self, IoRoute, oauth::Service};
fn error(e: Failure, callback: bool) -> Response {
    let status = if callback {
        StatusCode::BAD_REQUEST
    } else if e.0 == "invalid_gmail_legacy_request" {
        StatusCode::UNPROCESSABLE_ENTITY
    } else if e.0.contains("database_error")
        || e.0.contains("write_ack_failed")
        || e.0.contains("commit_outcome_unknown")
        || e.0 == "invalid_gmail_legacy_saved_record"
    {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::CONFLICT
    };
    reply(status, json!({"detail":e.0}))
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
    if let Err(e) = readiness(&mut c, &api.config).await {
        recovery::close(c).await;
        return Err(e);
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
            json!({"detail":"gmail_legacy_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("POST"));
        return response;
    }
    if query.is_some_and(|s| !s.is_empty()) {
        return error(Failure("invalid_gmail_legacy_request"), false);
    }
    let input = if matches!(route, IoRoute::Connect) {
        match serde_json::from_slice(body)
            .map_err(|_| Failure("invalid_gmail_legacy_request"))
            .and_then(gmail_legacy::connect)
        {
            Ok(v) => v,
            Err(e) => return error(e, false),
        }
    } else {
        if !body.is_empty()
            && !serde_json::from_slice::<Value>(body)
                .is_ok_and(|v| v.as_object().is_some_and(|o| o.is_empty()))
        {
            return error(Failure("invalid_gmail_legacy_request"), false);
        }
        Value::Null
    };
    if matches!(route, IoRoute::Connect) && input["authorization_mode"] == "send" {
        return error(Failure(gmail_legacy::SEND_BLOCKER), false);
    }
    let provider = api.config.mailboxes.provider().ok();
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
    let result = tokio::time::timeout(Duration::from_secs(100), async {
        match route {
            IoRoute::Disconnect => match provider {
                Some(provider) => {
                    Service {
                        settings: &api.config.gmail_accounts,
                        provider,
                    }
                    .disconnect(&mut c)
                    .await
                }
                None => {
                    gmail_legacy::refresh::disconnect_without_provider(
                        &mut c,
                        &api.config.gmail_accounts,
                    )
                    .await
                }
            },
            _ => {
                let provider = provider.ok_or(Failure("google_oauth_not_configured"))?;
                let service = Service {
                    settings: &api.config.gmail_accounts,
                    provider,
                };
                match route {
                    IoRoute::Connect => service.start(&mut c, input, &browser).await,
                    IoRoute::Verify => service.verify(&mut c).await,
                    IoRoute::Disconnect => unreachable!(),
                }
            }
        }
    })
    .await
    .unwrap_or(Err(Failure("gmail_legacy_operation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => {
            let mut response = reply(StatusCode::OK, value);
            if matches!(route, IoRoute::Connect) {
                cookie(
                    &mut response,
                    &browser,
                    api.config.gmail_accounts.ttl,
                    provider.is_some_and(|p| p.redirect_uri().starts_with("https:")),
                );
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
                .any(|(k, v)| k == "state" && !v.contains('.'))
        })
}
pub(super) async fn callback(api: &Api, request: Request) -> Response {
    let decoded = match crate::gmail_accounts::oauth::callback_prefix(request.uri().query(), "") {
        Ok(v) => v,
        Err(e) => return error(e, true),
    };
    let browser = match crate::gmail_accounts::oauth::browser_cookie(request.headers()) {
        Ok(v) => v,
        Err(e) => return error(e, true),
    };
    let host = match single(request.headers(), "host") {
        Some(v) => v,
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
    let service = Service {
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
    .unwrap_or(Err(Failure("gmail_legacy_operation_outcome_unknown")));
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
