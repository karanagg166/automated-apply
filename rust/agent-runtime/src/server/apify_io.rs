//! Owner-triggered metadata inspection uses the existing single transient connection permit.
use super::*;
use crate::apify_metadata::owner::{self, Route};
pub(super) async fn dispatch(
    api: &Api,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if route.method() != method {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"apify_metadata_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if query.is_some() || route != Route::Actor && !body.is_empty() {
        return profile_failure(Failure("apify_metadata_query_invalid"));
    }
    let actor = if route == Route::Actor {
        let value = match serde_json::from_slice::<Value>(body) {
            Ok(v) => v,
            Err(_) => return profile_failure(Failure("apify_actor_inspect_invalid")),
        };
        match crate::apify_metadata::inspect_request(&value) {
            Ok(s) => Some(s.to_owned()),
            Err(e) => return profile_failure(e),
        }
    } else {
        None
    };
    if actor
        .as_deref()
        .is_some_and(|s| !api.config.sources.actor_metadata_allowed(s))
    {
        return profile_failure(Failure("apify_actor_metadata_not_allowlisted"));
    }
    if route == Route::Account && !api.config.apify_metadata.token_configured() {
        return profile_failure(Failure("apify_local_token_not_configured"));
    }
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match api.config.connect(false).await {
        Ok(c) => c,
        Err(e) => return profile_failure(e),
    };
    let result = tokio::time::timeout(Duration::from_secs(30), async {
        readiness(&mut c, &api.config).await?;
        if route == Route::Status {
            owner::status(&mut c, &api.config.sources, &api.config.apify_metadata).await
        } else {
            owner::inspect(
                &mut c,
                &api.config.sources,
                &api.config.apify_metadata,
                actor.as_deref(),
            )
            .await
        }
    })
    .await
    .unwrap_or(Err(Failure("apify_metadata_timeout")));
    recovery::close(c).await;
    match result {
        Ok(v) => reply(StatusCode::OK, v),
        Err(e) => profile_failure(e),
    }
}
