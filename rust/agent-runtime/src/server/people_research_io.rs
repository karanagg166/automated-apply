//! Owner research shares the sole transient request slot; reads never execute provider work.
use super::*;
use crate::people_research::{controller::Service, owner::Route};
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
            json!({"detail":"public_research_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
    if query.is_some() || method == "GET" && !body.is_empty() {
        return profile_failure(Failure("invalid_public_research_query"));
    }
    match route {
        Route::Status => return reply(StatusCode::OK, api.config.people_research.status()),
        Route::Legacy => return profile_failure(Failure("public_research_request_id_required")),
        _ => {}
    }
    let Route::Request(id) = route else {
        return profile_failure(Failure("invalid_public_research_query"));
    };
    let input = if method == "PUT" {
        match serde_json::from_slice::<Value>(body) {
            Ok(v) => Some(v),
            Err(_) => return profile_failure(Failure("invalid_research_contract")),
        }
    } else {
        None
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
    let service = Service {
        settings: &api.config.people_research,
        client: api.config.people_search_client.as_ref(),
        contacts: &api.config.contacts,
    };
    let result = tokio::time::timeout(Duration::from_secs(60), async {
        readiness(&mut c, &api.config).await?;
        match input {
            Some(input) => service.run(&mut c, input, id).await,
            None => service.read(&mut c, id).await,
        }
    })
    .await
    .unwrap_or(Err(Failure("public_research_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(v) => reply(StatusCode::OK, v),
        Err(e) => profile_failure(e),
    }
}
