//! Legacy read OAuth/verify/disconnect share the single transient request permit.
use super::*;
use crate::gmail_accounts::{
    IoRoute,
    oauth::{self, Service},
};
fn error(error: Failure, callback: bool) -> Response {
    reply(
        if callback {
            StatusCode::BAD_REQUEST
        } else if error.0 == "invalid_gmail_read_contract" {
            StatusCode::UNPROCESSABLE_ENTITY
        } else if error.0.contains("database_error")
            || error.0.contains("write_ack_failed")
            || error.0.contains("commit_outcome_unknown")
            || error.0.starts_with("invalid_gmail_read_saved")
        {
            StatusCode::SERVICE_UNAVAILABLE
        } else {
            StatusCode::CONFLICT
        },
        json!({"detail":error.0}),
    )
}
async fn connection(api: &Api) -> Result<PgConnection> {
    let mut c = api.config.connect(false).await?;
    if let Err(e) = readiness(&mut c, &api.config).await {
        recovery::close(c).await;
        return Err(e);
    }
    Ok(c)
}
fn cookie(response: &mut Response, value: &str, ttl: i64, secure: bool) {
    if let Ok(header) = axum::http::HeaderValue::from_str(&format!(
        "gmail_oauth_browser={value}; HttpOnly; Max-Age={ttl}; Path={}; SameSite=Lax{}",
        crate::mailboxes::routes::CALLBACK,
        if secure { "; Secure" } else { "" }
    )) {
        response.headers_mut().append("set-cookie", header);
    }
}
pub(super) async fn dispatch(api: &Api, route: IoRoute, method: &str, body: &[u8]) -> Response {
    if method != "POST" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_read_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("POST"));
        return response;
    }
    let input = if matches!(route, IoRoute::Connect) {
        match serde_json::from_slice::<Value>(body)
            .map_err(|_| Failure("invalid_gmail_read_contract"))
            .and_then(|v| {
                crate::gmail_accounts::contract::normalize(
                    crate::gmail_accounts::contract::Kind::Connect,
                    v,
                )
            }) {
            Ok(v) => v,
            Err(e) => return error(e, false),
        }
    } else {
        if !body.is_empty()
            && !serde_json::from_slice::<Value>(body)
                .is_ok_and(|v| v.as_object().is_some_and(|o| o.is_empty()))
        {
            return error(Failure("invalid_gmail_read_contract"), false);
        }
        Value::Null
    };
    let provider = match api.config.mailboxes.provider() {
        Ok(p) => p,
        Err(e) => return error(e, false),
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
    let service = Service {
        settings: &api.config.gmail_accounts,
        provider,
    };
    let browser = crate::mailboxes::browser_nonce();
    let result = tokio::time::timeout(Duration::from_secs(65), async {
        match route {
            IoRoute::Connect => service.start(&mut c, input, None, &browser).await,
            IoRoute::Verify(id) => service.verify(&mut c, id).await,
            IoRoute::Disconnect(id) => service.disconnect(&mut c, id).await,
        }
    })
    .await
    .unwrap_or(Err(Failure("gmail_read_operation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => {
            let mut response = reply(StatusCode::OK, value);
            if matches!(route, IoRoute::Connect) {
                cookie(
                    &mut response,
                    &browser,
                    service.ttl(),
                    provider.redirect_uri().starts_with("https:"),
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
                .any(|(k, v)| k == "state" && v.starts_with("read."))
        })
}
pub(super) async fn callback(api: &Api, request: Request) -> Response {
    let decoded = match oauth::callback(request.uri().query()) {
        Ok(v) => v,
        Err(e) => return error(e, true),
    };
    let browser = match oauth::browser_cookie(request.headers()) {
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
    .unwrap_or(Err(Failure("gmail_read_operation_outcome_unknown")));
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
