//! Owner-only outreach preview/create shares the existing transient request budget.
use super::*;
use crate::outreach::{
    contract,
    controller::{Action, Service},
};
pub(super) async fn dispatch(
    api: &Api,
    action: Action,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if method != "POST" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"outreach_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("POST"));
        return response;
    }
    if query.is_some() {
        return profile_failure(Failure("invalid_outreach_query"));
    }
    let input = match serde_json::from_slice(body)
        .map_err(|_| Failure("invalid_outreach_contract"))
        .and_then(|v| contract::normalize(contract::Kind::Input, v))
    {
        Ok(value) => value,
        Err(e) => return profile_failure(e),
    };
    if input["use_llm"] == true && input["idempotency_key"].is_null() {
        return profile_failure(Failure("outreach_writer_idempotency_key_required"));
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
    let service = Service {
        contacts: &api.config.contacts,
        answers: &api.config.answers,
    };
    let result = tokio::time::timeout(Duration::from_secs(60), async {
        readiness(&mut c, &api.config).await?;
        service.run(&mut c, input, action, "rest").await
    })
    .await
    .unwrap_or(Err(Failure("outreach_generation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => reply(StatusCode::OK, value),
        Err(e) => profile_failure(e),
    }
}
