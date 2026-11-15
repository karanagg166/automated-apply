//! Bounded account operations share the existing transient-IO permit; Stop remains responsive.
use super::*;
use crate::mailboxes::{
    self, Service, Slot,
    routes::{self, Route},
};
fn error(error: Failure, callback: bool) -> Response {
    let status = if callback {
        StatusCode::BAD_REQUEST
    } else if matches!(error.0, "invalid_gmail_consent") {
        StatusCode::UNPROCESSABLE_ENTITY
    } else if matches!(
        error.0,
        "gmail_account_database_error"
            | "gmail_account_commit_outcome_unknown"
            | "invalid_gmail_account_record"
    ) {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::CONFLICT
    };
    reply(status, json!({"detail":error.0}))
}
async fn connection(api: &Api) -> Result<PgConnection> {
    let mut c = api.config.connect(false).await?;
    if let Err(error) = readiness(&mut c, &api.config).await {
        recovery::close(c).await;
        return Err(error);
    }
    Ok(c)
}
pub(super) async fn dispatch(api: &Api, route: Route, method: &str, body: &[u8]) -> Response {
    let expected = if matches!(route, Route::Accounts) {
        "GET"
    } else {
        "POST"
    };
    if method != expected {
        return reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_account_method_not_allowed"}),
        );
    }
    if !matches!(route, Route::Connect(_))
        && !body.is_empty()
        && !serde_json::from_slice::<Value>(body)
            .ok()
            .is_some_and(|v| v.as_object().is_some_and(|o| o.is_empty()))
    {
        return reply(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({"detail":"gmail_account_body_not_supported"}),
        );
    }
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match connection(api).await {
        Ok(c) => c,
        Err(failure) => return error(failure, false),
    };
    let settings = &api.config.mailboxes;
    let service = Service {
        settings,
        provider: settings,
    };
    let browser = mailboxes::browser_nonce();
    let result=tokio::time::timeout(Duration::from_secs(65),async {
        match route {
            Route::Accounts=>{
                let mut accounts=vec![];let slots=if settings.slots()==1{vec![Slot::One]}else{vec![Slot::One,Slot::Two]};
                for slot in slots {
                    let mut status=service.status(&mut c,slot).await?;
                    let raw:Option<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(format!("gm54_alerts:{}",slot.name())).fetch_optional(&mut c).await.map_err(|_|Failure("gmail_account_database_error"))?;
                    // Preserve the configured policy, without claiming an unported poller is running.
                    status["job_alerts"]=json!({"enabled":false,"configured_enabled":raw.as_ref().is_some_and(|v|v["enabled"]==true),"version":raw.as_ref().and_then(|v|v["version"].as_i64()).unwrap_or(0),"runtime_available":false,"sender":"naukrialerts@naukri.com","sending_enabled":false,"links_opened":false});accounts.push(status);
                }
                Ok(json!({"accounts":accounts,"sending_enabled":false,"monitoring_enabled":false}))
            }
            Route::Connect(slot)=>service.start(&mut c,slot,mailboxes::consent(body)?,&browser).await,
            Route::Verify(slot)=>service.verify(&mut c,slot).await,
            Route::Disconnect(slot)=>service.disconnect(&mut c,slot).await,
            Route::Callback=>Err(Failure("invalid_oauth_callback")),
        }
    }).await.unwrap_or(Err(Failure("gmail_account_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(data) => {
            let mut response = reply(StatusCode::OK, data);
            if let Route::Connect(slot) = route {
                set_cookie(
                    &mut response,
                    slot,
                    &browser,
                    settings.ttl(),
                    settings.secure_cookie(),
                );
            }
            response
        }
        Err(failure) => error(failure, false),
    }
}
fn set_cookie(response: &mut Response, slot: Slot, browser: &str, seconds: i64, secure: bool) {
    let value = format!(
        "gmail54_oauth_{}={browser}; HttpOnly; Max-Age={seconds}; Path={}; SameSite=Lax{}",
        slot.name(),
        routes::CALLBACK,
        if secure { "; Secure" } else { "" }
    );
    if let Ok(value) = axum::http::HeaderValue::from_str(&value) {
        response.headers_mut().append("set-cookie", value);
    }
}
pub(super) async fn callback(api: &Api, request: Request) -> Response {
    let decoded = match routes::callback(request.uri().query()) {
        Ok(value) => value,
        Err(failure) => return error(failure, true),
    };
    let cookie = match routes::browser_cookie(request.headers(), decoded.slot) {
        Ok(cookie) => cookie,
        Err(failure) => return error(failure, true),
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
    let uri = format!("{scheme}://{host}{}", routes::CALLBACK);
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match connection(api).await {
        Ok(c) => c,
        Err(failure) => return error(failure, true),
    };
    let settings = &api.config.mailboxes;
    let service = Service {
        settings,
        provider: settings,
    };
    let result = tokio::time::timeout(
        Duration::from_secs(65),
        service.callback(
            &mut c,
            &decoded.state,
            &cookie,
            &uri,
            decoded.code.as_deref(),
            decoded.error.as_deref(),
        ),
    )
    .await
    .unwrap_or(Err(Failure("gmail_account_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(data) => {
            let mut response = reply(
                StatusCode::OK,
                json!({"status":"connected","connection":data}),
            );
            set_cookie(&mut response, decoded.slot, "", 0, settings.secure_cookie());
            response
        }
        Err(failure) => error(failure, true),
    }
}
