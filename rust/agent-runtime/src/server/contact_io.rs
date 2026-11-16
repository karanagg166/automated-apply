//! Owner-only contact enrichment uses the shared transient permit, not the control mutex.
use super::*;
use crate::contacts::enrichment;
pub(super) async fn dispatch(
    api: &Api,
    company: Uuid,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if method != "POST" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"contact_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("POST"));
        return response;
    }
    if query.is_some() {
        return profile_failure(Failure("invalid_contact_query"));
    }
    let input = match serde_json::from_slice(body)
        .map_err(|_| Failure("invalid_contact_enrichment"))
        .and_then(enrichment::contract::normalize)
    {
        Ok(input) => input,
        Err(error) => return profile_failure(error),
    };
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"bounded_background_request_running"}),
        );
    };
    let mut c = match api.config.connect(false).await {
        Ok(c) => c,
        Err(error) => return profile_failure(error),
    };
    if let Err(error) = readiness(&mut c, &api.config).await {
        recovery::close(c).await;
        return profile_failure(error);
    }
    let service = enrichment::controller::Service {
        settings: &api.config.contact_enrichment,
        contacts: &api.config.contacts,
        clients: &api.config.contact_providers,
        eligibility: &api.config.apollo_eligibility,
    };
    let result = tokio::time::timeout(
        Duration::from_secs(90),
        service.enrich(&mut c, company, input),
    )
    .await
    .unwrap_or(Err(Failure("contact_enrichment_operation_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(value) => reply(StatusCode::OK, value),
        Err(error) => profile_failure(error),
    }
}
