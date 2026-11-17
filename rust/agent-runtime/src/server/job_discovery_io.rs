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
        match if matches!(
            route,
            Route::Complete(_) | Route::Read(_, _) | Route::CompleteRead(_, _)
        ) {
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
        Route::Read(parent, _) | Route::CompleteRead(parent, _) => Some(parent),
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
            // A bad optional paid configuration cannot hide saved terminal results or public routes.
            let disabled = crate::apify_jobs::settings::Settings::from_values(&Default::default())?;
            let paid = api.config.apify_jobs.as_ref().unwrap_or(&disabled);
            match route {
                Route::Read(parent,read) | Route::CompleteRead(parent,read) => {
                    if !matches!(owner::native_kind(&mut c,parent).await?,owner::NativeKind::Paid){
                        return Err(Failure("apify_read_native_owner_required"));
                    }
                    crate::apify_jobs::runs::read(&mut c,parent).await?;
                    if method=="GET" {
                        crate::apify_jobs::read_admission::read(&mut c,parent,read).await
                    } else if matches!(route,Route::CompleteRead(_,_)) {
                        crate::apify_jobs::read_controller::finish(&mut c,paid,parent,read).await
                    } else {
                        crate::apify_jobs::read_controller::Service{settings:paid,client:&api.config.apify_jobs_client}
                            .recover(&mut c,parent,read).await
                    }
                }
                Route::Preview => {
                    let input=input.expect("preview input");
                    let mut out=owner::preview(&mut c,&api.config.sources,input.clone()).await?;
                    if crate::source_registry::APIFY_PORTALS.contains(&input["source"].as_str().unwrap_or("")) {
                        let selected=paid.preview(input["source"].as_str().expect("validated source"),out["query"].clone(),input["allow_paid"]==true,chrono::Utc::now());
                        out["estimated_usd"]=selected["estimated_usd"].as_str().and_then(|s|s.parse::<f64>().ok()).map(|v|json!(v)).unwrap_or(Value::Null);
                        out["paid_execution"]=selected;
                        out["message"]=json!("Planning only; no provider call or budget reservation. The full run cap remains reserved after an uncertain start.");
                    }
                    Ok(out)
                }
                Route::Run(id) if method == "GET" => owner::read(&mut c, id).await,
                Route::Complete(id) => match owner::native_kind(&mut c,id).await? {
                    owner::NativeKind::Paid=>crate::apify_jobs::runs::finish(&mut c,paid,id).await,
                    _=>runs::finish(&mut c,&api.config.sources,id).await,
                },
                _ => {
                    let input=input.expect("run input");
                    if crate::source_registry::APIFY_PORTALS.contains(&input["source"].as_str().unwrap_or("")) {
                        return crate::apify_jobs::runs::Service{settings:paid,client:&api.config.apify_jobs_client}
                            .run(&mut c,input,id.expect("run id")).await;
                    }
                    runs::Service {
                        settings: &api.config.sources,
                        client: &api.config.public_jobs,
                        timeout_seconds: api.config.discovery_timeout_seconds,
                    }
                    .run(&mut c, input, id.expect("run id"))
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
