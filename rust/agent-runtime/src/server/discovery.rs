//! Public feed IO releases the control connection while waiting on the provider.
use super::{Api, reply};
use crate::Failure;
use axum::{http::StatusCode, response::Response};
use serde_json::json;

fn unavailable(error: Failure) -> Response {
    reply(StatusCode::SERVICE_UNAVAILABLE, json!({"error":error.0}))
}

pub(super) async fn ingest(api: &Api, platform: &str, body: &[u8]) -> Response {
    let platform = match crate::public_discovery::Platform::parse(platform) {
        Ok(p) => p,
        Err(e) => return reply(StatusCode::NOT_FOUND, json!({"error":e.0})),
    };
    let input = match crate::feed_ingestion::request(body) {
        Ok(p) => p,
        Err(e) => return reply(StatusCode::UNPROCESSABLE_ENTITY, json!({"error":e.0})),
    };
    let mut state = api.connection.lock().await;
    let connection = match state.ready(&api.config).await {
        Ok(connection) => connection,
        Err(error) => return unavailable(error),
    };
    let result = crate::feed_ingestion::ingest(connection, platform, input).await;
    state.finish(&result).await;
    match result {
        Ok(value) => reply(StatusCode::OK, value),
        Err(e) => reply(
            if matches!(
                e.0,
                "feed_batch_changed"
                    | "feed_batch_stale"
                    | "feed_identity_conflict"
                    | "feed_ingestion_write_ack_failed"
            ) {
                StatusCode::CONFLICT
            } else {
                StatusCode::SERVICE_UNAVAILABLE
            },
            json!({"error":e.0}),
        ),
    }
}

pub(super) async fn dispatch(api: &Api, platform: &str, body: &[u8]) -> Response {
    use crate::public_discovery::{self, Reservation};
    let fail = |error: Failure| {
        let status = match error.0 {
            "invalid_public_feed_request" => StatusCode::UNPROCESSABLE_ENTITY,
            "unsupported_public_feed" => StatusCode::NOT_FOUND,
            "public_feed_cooldown" | "public_feed_rate_limited" | "public_feed_busy" => {
                StatusCode::TOO_MANY_REQUESTS
            }
            "public_feed_write_ack_failed" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        reply(status, json!({"error":error.0}))
    };
    let Ok(_permit) = api.public_request.try_acquire() else {
        return fail(Failure("public_feed_busy"));
    };
    let platform = match public_discovery::Platform::parse(platform) {
        Ok(p) => p,
        Err(e) => return fail(e),
    };
    let input = match public_discovery::request(body) {
        Ok(i) => i,
        Err(e) => return fail(e),
    };
    let reserved = {
        let mut state = api.connection.lock().await;
        let connection = match state.ready(&api.config).await {
            Ok(connection) => connection,
            Err(error) => return fail(error),
        };
        let result = public_discovery::reserve(connection, platform, input.limit).await;
        state.finish(&result).await;
        result
    };
    let (token, record) = match reserved {
        Ok(Reservation::Cached(data)) => return reply(StatusCode::OK, data),
        Ok(Reservation::Fetch { token, record }) => (token, record),
        Err(error) => return fail(error),
    };
    // No database connection mutex or transaction is held across provider IO.
    let fetched = public_discovery::fetch(platform).await;
    let mut state = api.connection.lock().await;
    let connection = match state.ready(&api.config).await {
        Ok(connection) => connection,
        Err(error) => return fail(error),
    };
    let result =
        public_discovery::finish(connection, platform, token, record, fetched, input.limit).await;
    state.finish(&result).await;
    match result {
        Ok(data) => reply(StatusCode::OK, data),
        Err(error) => fail(error),
    }
}

pub(super) async fn schedule(api: &Api, method: &str, body: &[u8]) -> Response {
    if !matches!(method, "GET" | "PUT") {
        return reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"error":"schedule_method_not_allowed"}),
        );
    }
    let update = if method == "PUT" {
        match crate::discovery_schedule::request(body) {
            Ok(value) => Some(value),
            Err(e) => return reply(StatusCode::UNPROCESSABLE_ENTITY, json!({"error":e.0})),
        }
    } else {
        None
    };
    let mut state = api.connection.lock().await;
    let c = match state.ready(&api.config).await {
        Ok(connection) => connection,
        Err(error) => return unavailable(error),
    };
    let result = if let Some(update) = update {
        match crate::discovery_schedule::update(c, update).await {
            Ok(_) => crate::discovery_schedule::status(c).await,
            Err(e) => Err(e),
        }
    } else {
        crate::discovery_schedule::status(c).await
    };
    state.finish(&result).await;
    match result {
        Ok(policy) => {
            if method == "PUT" {
                api.wake.work_available();
            }
            reply(StatusCode::OK, json!(policy))
        }
        Err(e) => reply(
            if matches!(
                e.0,
                "discovery_schedule_revision_conflict" | "discovery_schedule_write_ack_failed"
            ) {
                StatusCode::CONFLICT
            } else {
                StatusCode::SERVICE_UNAVAILABLE
            },
            json!({"error":e.0}),
        ),
    }
}
