//! Reuses the sole transient host permit; startup preview never takes the owner mutex.
use super::*;
use crate::startup_catalog::owner::Route;
pub(super) async fn dispatch(
    api: &Api,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Response {
    if method != route.method() {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"startup_catalog_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if query.is_some() || method == "GET" && !body.is_empty() {
        return profile_failure(Failure("invalid_startup_query"));
    }
    match route {
        Route::Sources => {
            return reply(
                StatusCode::OK,
                api.config.sources.startups(chrono::Utc::now()),
            );
        }
        Route::JobSources => {
            return reply(StatusCode::OK, api.config.sources.jobs(chrono::Utc::now()));
        }
        _ => {}
    }
    let input = if method == "POST" {
        match serde_json::from_slice::<Value>(body) {
            Ok(v) => Some(v),
            Err(_) => return profile_failure(Failure("invalid_startup_contract")),
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
    let result = tokio::time::timeout(
        Duration::from_secs_f64(api.config.discovery_timeout_seconds + 10.0),
        async {
            readiness(&mut c, &api.config).await?;
            match route {
                Route::Preview => {
                    crate::startup_catalog::owner::preview(
                        &mut c,
                        input.unwrap(),
                        &api.config.sources,
                    )
                    .await
                }
                Route::Run(id) => {
                    crate::startup_catalog::runs::read(
                        &mut c,
                        id,
                        api.config.discovery_timeout_seconds,
                    )
                    .await
                }
                Route::Runs => {
                    let raw = input.unwrap();
                    let value = crate::research_contract::normalize(
                        crate::research_contract::Kind::StartupRun,
                        raw.clone(),
                        chrono::Utc::now(),
                    )?;
                    api.config.sources.startup(
                        value["source"]
                            .as_str()
                            .ok_or(Failure("invalid_startup_contract"))?,
                        chrono::Utc::now(),
                    )?;
                    if value["mode"] == "job_led" {
                        let id = crate::startup_catalog::job_led::request_id(&value)?;
                        return crate::startup_catalog::job_led::Service {
                            sources: &api.config.sources,
                            client: &api.config.public_jobs,
                            contacts: &api.config.contacts,
                            timeout_seconds: api.config.discovery_timeout_seconds,
                        }
                        .run_with_paid(
                            &mut c,
                            raw,
                            id,
                            api.config.apify_jobs.as_ref(),
                            Some(&api.config.apify_jobs_client),
                        )
                        .await;
                    }
                    if value["source"] != "manual" || value["mode"] != "company_first" {
                        return Err(Failure("startup_provider_orchestration_not_implemented"));
                    }
                    crate::startup_catalog::runs::run_manual(
                        &mut c,
                        raw,
                        &api.config.contacts,
                        api.config.discovery_timeout_seconds,
                    )
                    .await
                }
                _ => Err(Failure("startup_source_unknown")),
            }
        },
    )
    .await
    .unwrap_or(Err(Failure("startup_run_outcome_unknown")));
    recovery::close(c).await;
    match result {
        Ok(v) => reply(StatusCode::OK, v),
        Err(e) => profile_failure(e),
    }
}
