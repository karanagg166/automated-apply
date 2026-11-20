//! One shared transient connection for bounded inference or private document IO.
use super::*;

pub(super) async fn project_build_dispatch(
    api: &Api,
    project_id: &str,
    body: &[u8],
    query: Option<&str>,
) -> Response {
    use crate::project_context::dashboard::builder;

    let input = match builder::Input::parse(body, query) {
        Ok(input) => input,
        Err(error) => return profile_failure(error),
    };
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"A bounded background request is already running"}),
        );
    };
    match builder::execute(&api.config, project_id, input).await {
        Ok(data) => reply(StatusCode::OK, data),
        Err(error) => profile_failure(error),
    }
}

pub(super) async fn generation_dispatch(
    api: &Api,
    body: &[u8],
    packet: Option<(Uuid, Uuid)>,
) -> Response {
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"An answer generation is already running"}),
        );
    };
    let input = match serde_json::from_slice::<Value>(body) {
        Ok(input)
            if if packet.is_some() {
                crate::packet_generation::request(input.clone()).is_ok()
            } else {
                crate::answer_contract::normalize(input.clone()).is_ok()
            } =>
        {
            input
        }
        _ => return profile_failure(Failure("invalid_answer_request")),
    };
    let mut connection = match api.config.connect(false).await {
        Ok(connection) => connection,
        Err(error) => return profile_failure(error),
    };
    let result = tokio::time::timeout(Duration::from_secs(40), async {
        readiness(&mut connection, &api.config).await?;
        if let Some((packet, field)) = packet {
            crate::packet_generation::generate(
                &mut connection,
                packet,
                field,
                crate::packet_generation::request(input)?,
                &api.config.packets,
                &api.config.answers,
            )
            .await
        } else {
            crate::answer_service::generate(&mut connection, input, &api.config.answers).await
        }
    })
    .await
    .unwrap_or(Err(Failure("generation_outcome_unknown")));
    recovery::close(connection).await;
    match result {
        Ok(data) => reply(StatusCode::OK, data),
        Err(error) => profile_failure(error),
    }
}
pub(super) enum ResumeIo<'a> {
    Upload(&'a str, &'a [u8]),
    Download(Uuid),
}
enum ResumeOutput {
    Upload(Value),
    Download(Vec<u8>),
}
pub(super) async fn resume_io_dispatch(api: &Api, input: ResumeIo<'_>) -> Response {
    let Ok(_permit) = api.long_request.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"detail":"A bounded background request is already running"}),
        );
    };
    let mut connection = match api.config.connect(false).await {
        Ok(c) => c,
        Err(error) => return profile_failure(error),
    };
    let result = tokio::time::timeout(Duration::from_secs(40), async {
        readiness(&mut connection, &api.config).await?;
        match input {
            ResumeIo::Upload(label, body) => {
                crate::private_resume::upload(&mut connection, label, body, &api.config.resumes)
                    .await
                    .map(ResumeOutput::Upload)
            }
            ResumeIo::Download(id) => {
                crate::private_resume::download(&mut connection, id, &api.config.resumes)
                    .await
                    .map(ResumeOutput::Download)
            }
        }
    })
    .await
    .unwrap_or(Err(Failure("private_resume_outcome_unknown")));
    recovery::close(connection).await;
    match result {
        Ok(ResumeOutput::Upload(data)) => reply(StatusCode::CREATED, data),
        Ok(ResumeOutput::Download(raw)) => pdf_reply(raw),
        Err(error) => profile_failure(error),
    }
}
fn pdf_reply(raw: Vec<u8>) -> Response {
    let mut response = (StatusCode::OK, raw).into_response();
    for (key, value) in [
        ("content-type", "application/pdf"),
        ("content-disposition", "attachment; filename=\"resume.pdf\""),
        ("cache-control", "private, no-store"),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "no-referrer"),
    ] {
        response.headers_mut().insert(
            axum::http::HeaderName::from_static(key),
            axum::http::HeaderValue::from_static(value),
        );
    }
    response
}
