//! Owner public discovery shares the single transient permit; GET and preview cannot dispatch.
use super::*;
use crate::job_sources::{
    owner::{self, Route},
    runs,
};
pub(super) async fn dispatch(
    api: &Api,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if !route.accepts(method) {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"discovery_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
    if query.is_some() || method == "GET" && !body.is_empty() {
        return profile_failure(Failure("invalid_discovery_query"));
    }
    let input = if method != "GET" {
        let value = match serde_json::from_slice::<Value>(body) {
            Ok(v) => v,
            Err(_) => return profile_failure(Failure("invalid_discovery_run_request")),
        };
        match if matches!(route, Route::Complete(_)) {
            if value == json!({}) {
                Ok(value)
            } else {
                Err(Failure("invalid_discovery_query"))
            }
        } else if route == Route::Preview {
            owner::request(value)
        } else {
            owner::execution_request(value)
        } {
            Ok(v) => Some(v),
            Err(e) => return profile_failure(e),
        }
    } else {
        None
    };
    let id = match route {
        Route::Run(id) | Route::Complete(id) => Some(id),
        Route::Runs => match owner::compatibility_id(input.as_ref().expect("POST input")) {
            Ok(id) => Some(id),
            Err(e) => return profile_failure(e),
        },
        Route::Preview => None,
    };
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
    let result = tokio::time::timeout(
        Duration::from_secs_f64(api.config.discovery_timeout_seconds + 10.0),
        async {
            readiness(&mut c, &api.config).await?;
            match route {
                Route::Preview => {
                    owner::preview(&mut c, &api.config.sources, input.expect("preview input")).await
                }
                Route::Run(id) if method == "GET" => owner::read(&mut c, id).await,
                Route::Complete(id) => runs::finish(&mut c, &api.config.sources, id).await,
                _ => {
                    runs::Service {
                        settings: &api.config.sources,
                        client: &api.config.public_jobs,
                        timeout_seconds: api.config.discovery_timeout_seconds,
                    }
                    .run(&mut c, input.expect("run input"), id.expect("run id"))
                    .await
                }
            }
        },
    )
    .await
    .unwrap_or(Err(Failure("discovery_run_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(v) => reply(StatusCode::OK, v),
        Err(e) => profile_failure(e),
    }
}
