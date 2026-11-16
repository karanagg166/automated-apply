//! Owner HTTP request orchestration; domain services own transactions and behavior.
use super::*;

pub(super) async fn handle(State(api): State<Arc<Api>>, request: Request) -> Response {
    let is_profile = profile_route(request.uri().path());
    let fail = |error| {
        if is_profile {
            profile_failure(error)
        } else {
            failure(error)
        }
    };
    let Ok(_permit) = api.requests.try_acquire() else {
        return reply(
            StatusCode::TOO_MANY_REQUESTS,
            json!({"error":"owner_api_busy"}),
        );
    };
    if let Err(error) = authorize(&request, &api.config) {
        return fail(error);
    }
    let method = request.method().as_str().to_owned();
    let path = request.uri().path().to_owned();
    if let Some(route) = crate::gmail_legacy::route(&path) {
        if route.method() != method {
            let mut response = reply(
                StatusCode::METHOD_NOT_ALLOWED,
                json!({"detail":"gmail_legacy_method_not_allowed"}),
            );
            response.headers_mut().insert(
                "allow",
                axum::http::HeaderValue::from_static(route.method()),
            );
            return response;
        }
        if matches!(route, crate::gmail_legacy::Route::SendRefusal) {
            return reply(
                StatusCode::CONFLICT,
                json!({"detail":{"code":"send_blocked","blockers":[crate::gmail_legacy::SEND_BLOCKER]}}),
            );
        }
    }
    let packet_query = request.uri().query().map(str::to_owned);
    let job_page = match crate::job_catalog::Page::parse(
        if path == crate::job_catalog::JOBS && method == "GET" {
            request.uri().query()
        } else {
            None
        },
    ) {
        Ok(page) => page,
        Err(error) => return fail(error),
    };
    let pdf_upload = path == "/api/v1/dashboard/resumes" && method == "POST";
    let label = if pdf_upload {
        match resume_label(request.uri().query()) {
            Ok(label) => Some(label),
            Err(error) => return fail(error),
        }
    } else {
        None
    };
    if pdf_upload
        && single(request.headers(), "content-type").and_then(|s| s.split(';').next())
            != Some("application/pdf")
    {
        return fail(Failure("pdf_content_type_required"));
    }
    if method == "GET" && path == "/health" {
        return reply(
            StatusCode::OK,
            json!({"alive":true,"scope":"saved_job_review_no_application_dispatch"}),
        );
    }
    if method == "GET" && path == crate::mailboxes::routes::CALLBACK {
        return accounts::callback(&api, request).await;
    }
    if let Some(route) = crate::browser_profiles::route(&path)
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"browser_profile_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if let Some(route) = crate::execution::route(&path).map(|route| route.for_method(&method))
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"execution_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
    if let Some(route) = crate::gmail_accounts::route(&path)
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_read_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if let Some(route) = crate::gmail_workspace::route(&path)
        && !route.accepts(&method)
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_workspace_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(match route {
                crate::gmail_workspace::Route::Accounts => "GET",
                crate::gmail_workspace::Route::Drafts => "GET, POST",
                crate::gmail_workspace::Route::Draft(_) => "PUT",
            }),
        );
        return response;
    }
    if let Some(route) = crate::gmail_history::route(&path)
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"gmail_history_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if let Some(route) = crate::resume_review::route(&path)
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"resume_review_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    let selected = match selected_resource(&path, &method, request.uri().query()) {
        Ok(selected) => selected,
        Err(error) => return fail(error),
    };
    let page = if paginated(&path) {
        match resource_page(&path, &method, request.uri().query()) {
            Ok(page) => page,
            Err(error) => return fail(error),
        }
    } else {
        (0, 25)
    };
    let if_match = if request.headers().contains_key("if-match") {
        Some(
            single(request.headers(), "if-match")
                .unwrap_or("")
                .to_owned(),
        )
    } else {
        None
    };
    let signature = single(request.headers(), "x-browser-owner-approval").map(str::to_owned);
    let body = match tokio::time::timeout(
        Duration::from_secs(20),
        to_bytes(
            request.into_body(),
            if pdf_upload {
                crate::private_resume::MAX_PDF
            } else if matches!(
                crate::resume_review::route(&path),
                Some(crate::resume_review::Route::Approve(_))
            ) {
                1048576
            } else {
                65536
            },
        ),
    )
    .await
    {
        Ok(Ok(body)) => body,
        Ok(Err(_)) => {
            return reply(
                StatusCode::PAYLOAD_TOO_LARGE,
                if is_profile {
                    json!({"detail":if pdf_upload{"PDF exceeds 5 MiB"}else{"Profile request exceeds 64 KiB"}})
                } else {
                    json!({"error":"owner_request_too_large"})
                },
            );
        }
        Err(_) => {
            return reply(
                StatusCode::REQUEST_TIMEOUT,
                json!({"error":"owner_request_timeout"}),
            );
        }
    };
    let proof = if crate::http_policy::requires_owner_approval(&path, &method) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(f64::NAN);
        match api
            .config
            .owner_signing
            .as_ref()
            .ok_or(Failure("owner_approval_unavailable"))
            .and_then(|key| key.verify_at(&path, &body, signature.as_deref().unwrap_or(""), now))
        {
            Ok(proof) => Some(proof),
            Err(error) => return fail(error),
        }
    } else {
        None
    };
    if let Some(route) = crate::gmail_accounts::io_route(&path) {
        return gmail_accounts_io::dispatch(&api, route, &method, &body).await;
    }
    if let Some(route) = crate::gmail_workspace::io_route(&path) {
        return gmail_workspace_io::dispatch(&api, route, &method, packet_query.as_deref(), &body)
            .await;
    }
    if let Some(route) = crate::mailboxes::routes::route(&path) {
        return accounts::dispatch(&api, route, &method, &body).await;
    }
    if path == "/api/v1/rust-agent/discovery/schedule" {
        return discovery::schedule(&api, &method, &body).await;
    }
    if let Some(platform) = crate::feed_ingestion::route(&path) {
        if method != "POST" {
            return reply(
                StatusCode::METHOD_NOT_ALLOWED,
                json!({"error":"public_feed_method_not_allowed"}),
            );
        }
        return discovery::ingest(&api, platform, &body).await;
    }
    if let Some(platform) = crate::public_discovery::route(&path) {
        if method != "POST" {
            return reply(
                StatusCode::METHOD_NOT_ALLOWED,
                json!({"error":"public_feed_method_not_allowed"}),
            );
        }
        return discovery::dispatch(&api, platform, &body).await;
    }
    if path == "/api/v1/application-answers/generate" {
        if method != "POST" {
            return fail(Failure("match_method_not_allowed"));
        }
        return generation_dispatch(&api, &body, None).await;
    }
    if let Some((packet, field)) = crate::packet_generation::route(&path) {
        if method != "POST" {
            return fail(Failure("packet_method_not_allowed"));
        }
        let ids = packet
            .parse::<Uuid>()
            .and_then(|packet| field.parse::<Uuid>().map(|field| (packet, field)));
        return match ids {
            Ok(ids) => generation_dispatch(&api, &body, Some(ids)).await,
            Err(_) => fail(Failure("invalid_packet_id")),
        };
    }
    if let Some(label) = label {
        return resume_io_dispatch(&api, ResumeIo::Upload(&label, &body)).await;
    }
    if let Some((id, "")) = resume_route(&path)
        && !id.is_empty()
        && method == "GET"
    {
        return match id.parse() {
            Ok(id) => resume_io_dispatch(&api, ResumeIo::Download(id)).await,
            Err(_) => fail(Failure("private_resume_not_found")),
        };
    }
    let mut state = api.connection.lock().await;
    if state.value.is_none() {
        if !state.backoff.remaining().is_zero() {
            return fail(Failure("agent_database_reconnecting"));
        }
        match api.config.connect(false).await {
            Ok(mut connection) => {
                if let Err(error) = readiness(&mut connection, &api.config).await {
                    recovery::close(connection).await;
                    state.backoff.failed();
                    return fail(error);
                }
                state.value = Some(connection);
            }
            Err(error) => {
                state.backoff.failed();
                return fail(error);
            }
        }
    }
    let mut result = match state.value.as_mut() {
        Some(connection) if crate::execution::route(&path).is_some() => {
            crate::execution::dispatch_body_configured(
                connection,
                crate::execution::route(&path).unwrap().for_method(&method),
                &method,
                packet_query.as_deref(),
                &body,
                Some(&api.config),
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::from_u16(crate::execution::route(&path).unwrap().status())
                    .unwrap_or(StatusCode::OK),
                etag: None,
            })
        }
        Some(connection) if crate::browser_profiles::route(&path).is_some() => {
            crate::browser_profiles::dispatch(
                connection,
                crate::browser_profiles::route(&path).unwrap(),
                &method,
                &body,
                &api.config.browser_profiles,
                &api.config.packets,
                Some(crate::browser_profiles::form_service::Services {
                    answers: &api.config.answers,
                    resumes: &api.config.resumes,
                }),
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::resume_review::route(&path).is_some() => {
            crate::resume_review::dispatch(
                connection,
                crate::resume_review::route(&path).unwrap(),
                &method,
                &body,
                &api.config.resume_review,
                &api.config.resumes,
                api.config.profile_live,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::gmail_accounts::route(&path).is_some() => {
            crate::gmail_accounts::dispatch(
                connection,
                crate::gmail_accounts::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.gmail_accounts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::gmail_workspace::route(&path).is_some() => {
            crate::gmail_workspace::dispatch(
                connection,
                crate::gmail_workspace::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.gmail_accounts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection)
            if matches!(
                crate::gmail_legacy::route(&path),
                Some(crate::gmail_legacy::Route::Status)
            ) =>
        {
            if method != "GET" {
                Err(Failure("gmail_legacy_method_not_allowed"))
            } else if packet_query.as_ref().is_some_and(|s| !s.is_empty()) || !body.is_empty() {
                Err(Failure("invalid_gmail_legacy_request"))
            } else {
                crate::gmail_legacy::status(
                    connection,
                    &api.config.gmail_accounts,
                    api.config.mailboxes.provider().is_ok(),
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            }
        }
        Some(connection) if crate::gmail_history::route(&path).is_some() => {
            crate::gmail_history::dispatch(
                connection,
                crate::gmail_history::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if path == crate::notification_preferences::PATH => {
            crate::notification_preferences::dispatch(connection, &method, &body)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if crate::packet_service::route(&path).is_some() => {
            crate::packet_service::dispatch(
                connection,
                &method,
                &path,
                packet_query.as_deref(),
                &body,
                &api.config.packets,
                &api.config.answers,
            )
            .await
            .map(|(data, created)| OwnerReply {
                data,
                status: if created {
                    StatusCode::CREATED
                } else {
                    StatusCode::OK
                },
                etag: None,
            })
        }
        Some(connection) if crate::job_catalog::route(&path).is_some() => {
            crate::job_catalog::dispatch(connection, &method, &path, &job_page)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if crate::notifications::route(&path).is_some() => {
            crate::notifications::dispatch(connection, &method, &path, page.0)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if resume_route(&path).is_some() => {
            let (id, action) = resume_route(&path).unwrap();
            if id.is_empty() && method == "GET" {
                crate::private_resume::listing(connection)
                    .await
                    .map(|data| OwnerReply {
                        data,
                        status: StatusCode::OK,
                        etag: None,
                    })
            } else if let Ok(id) = id.parse::<Uuid>() {
                if action == "confirm" && method == "POST" {
                    match serde_json::from_slice(&body)
                        .map_err(|_| Failure("invalid_resume_confirmation"))
                        .and_then(crate::private_resume::confirmation)
                    {
                        Ok(input) => crate::private_resume::confirm(
                            connection,
                            id,
                            input,
                            &api.config.resumes,
                        )
                        .await
                        .map(|data| OwnerReply {
                            data,
                            status: StatusCode::OK,
                            etag: None,
                        }),
                        Err(error) => Err(error),
                    }
                } else {
                    Err(Failure("resume_method_not_allowed"))
                }
            } else if id.is_empty() {
                Err(Failure("resume_method_not_allowed"))
            } else {
                Err(Failure("private_resume_not_found"))
            }
        }
        Some(connection) if path == "/api/v1/profile" => {
            profile_dispatch(
                connection,
                &method,
                &body,
                if_match.as_deref(),
                api.config.profile_live,
            )
            .await
        }
        Some(connection) if resource_inspection(&path) => {
            if method != "GET" {
                Err(Failure("resource_read_method_not_allowed"))
            } else {
                crate::resource_store::inspect(
                    connection,
                    selected,
                    path.ends_with("profile-readiness"),
                    api.config.profile_live,
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            }
        }
        Some(connection) if candidate_resource_route(&path) => {
            candidate_resource_dispatch(connection, &method, &path, &body, page, &api.config).await
        }
        Some(connection) if missing_route(&path) => {
            missing_dispatch(connection, &method, &path, &body, page, proof).await
        }
        Some(connection) if draft_route(&path) => {
            let data = if let Some((id, action)) = draft_action(&path) {
                match id.parse::<Uuid>() {
                    Err(_) => Err(Failure("invalid_answer_draft_review")),
                    Ok(id) => match (method.as_str(), action) {
                        ("POST", "approve-reuse") => {
                            match serde_json::from_slice(&body)
                                .map_err(|_| Failure("invalid_answer_reuse_approval"))
                                .and_then(crate::answer_reuse::approval_input)
                            {
                                Ok(input) => match proof {
                                    Some(proof) => {
                                        crate::answer_reuse::approve(
                                            connection,
                                            id,
                                            input,
                                            proof,
                                            api.config.answers.reuse,
                                            api.config.answers.opportunity,
                                        )
                                        .await
                                    }
                                    None => Err(Failure("owner_approval_required")),
                                },
                                Err(error) => Err(error),
                            }
                        }
                        ("POST", "revoke-reuse") => {
                            crate::answer_reuse::revoke(connection, id).await
                        }
                        ("GET", "opportunity-evidence") => {
                            crate::answer_reuse::opportunity_evidence(connection, id).await
                        }
                        (_, "opportunity-evidence") => {
                            Err(Failure("resource_read_method_not_allowed"))
                        }
                        _ => Err(Failure("match_method_not_allowed")),
                    },
                }
            } else if path == "/api/v1/application-answers/drafts" {
                if method != "GET" {
                    Err(Failure("resource_read_method_not_allowed"))
                } else {
                    crate::answer_store::list(connection, page.0, page.1).await
                }
            } else if method != "PATCH" {
                Err(Failure("evidence_patch_method_not_allowed"))
            } else {
                match (
                    draft_id(&path).unwrap().parse::<Uuid>(),
                    serde_json::from_slice::<crate::answer_store::Review>(&body),
                ) {
                    (Ok(id), Ok(input)) => crate::answer_store::review(connection, id, input).await,
                    _ => Err(Failure("invalid_answer_draft_review")),
                }
            };
            data.map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if path == "/api/v1/application-answers/reuse-approvals" => {
            if method != "GET" {
                Err(Failure("resource_read_method_not_allowed"))
            } else {
                crate::answer_reuse::approvals(
                    connection,
                    api.config.answers.reuse,
                    api.config.owner_signing.is_some(),
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            }
        }
        Some(connection) if path == "/api/v1/local-agent/profile-confirmation" => {
            if method != "POST" {
                Err(Failure("match_method_not_allowed"))
            } else {
                match serde_json::from_slice::<crate::profile_confirmation::Confirmation>(&body) {
                    Ok(input) => crate::profile_confirmation::confirm(connection, input)
                        .await
                        .map(|data| {
                            api.wake.work_available();
                            OwnerReply {
                                data,
                                status: StatusCode::OK,
                                etag: None,
                            }
                        }),
                    Err(_) => Err(Failure("invalid_profile_confirmation")),
                }
            }
        }
        Some(connection) if saved_match_route(&path).is_some() => {
            if !matches!(method.as_str(), "GET" | "POST") {
                Err(Failure("saved_match_method_not_allowed"))
            } else if let Ok(id) = saved_match_route(&path).unwrap().parse::<Uuid>() {
                let result = if method == "GET" {
                    crate::saved_match::read_calculate(connection, id).await
                } else {
                    crate::saved_match::calculate(connection, id).await
                };
                result
                    .map_err(|error| {
                        if method == "GET"
                            && matches!(error.0, "job_not_found" | "profile_not_found")
                        {
                            Failure("saved_record_not_found")
                        } else {
                            error
                        }
                    })
                    .map(|data| OwnerReply {
                        data,
                        status: StatusCode::OK,
                        etag: None,
                    })
            } else {
                Err(Failure("invalid_job_id"))
            }
        }
        Some(connection) => dispatch(&api, connection, &method, &path, &body)
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            }),
        None => Err(Failure("agent_database_unavailable")),
    };
    // Flush any rollback queued by a rejected operation's transaction Drop before
    // retaining this connection idle. This prevents cross-request lock retention.
    if result.is_err()
        && let Some(connection) = state.value.as_mut()
        && connection.ping().await.is_err()
    {
        result = Err(Failure("profile_database_error"));
    }
    if result
        .as_ref()
        .err()
        .is_some_and(|error| recovery::database_failure(*error))
    {
        if let Some(connection) = state.value.take() {
            recovery::close(connection).await;
        }
        state.backoff.failed();
    } else if result.is_ok() {
        state.backoff.reset();
    }
    if method != "GET"
        && result.as_ref().is_ok_and(|r| r.data["ok"] != false)
        && (crate::execution::route(&path).is_some()
            || path == crate::browser_profiles::NATIVE
                && result
                    .as_ref()
                    .is_ok_and(|r| r.data["data"]["work"]["status"] == "queued"))
    {
        api.wake.work_available();
    }
    match result {
        Ok(result) => {
            let mut response = reply(result.status, result.data);
            if let Some(etag) = result.etag {
                response.headers_mut().insert("etag", etag.parse().unwrap());
            }
            response
        }
        Err(error) => fail(error),
    }
}
