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
    let candidate_context = crate::project_context::dashboard::route(&path);
    if let Some(route) = candidate_context
        && !route.allows(&method)
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"project_context_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
    let local_command_route = crate::owner_commands::route(&path);
    if let Some(route) = local_command_route
        && method != route.method()
    {
        let mut response = fail(Failure("local_command_method_not_allowed"));
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    let platform_session_route = crate::platform_sessions::route(&path);
    if let Some(route) = platform_session_route
        && method != route.method()
    {
        let mut response = fail(Failure("platform_session_method_not_allowed"));
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    let startup_allow = crate::startup_catalog::search::route(&path)
        .map(|r| {
            if matches!(r, crate::startup_catalog::search::Route::Search) {
                "GET, POST"
            } else {
                "GET"
            }
        })
        .or_else(|| crate::startup_catalog::shortlist::route(&path).map(|_| "POST"));
    if let Some(allow) = startup_allow
        && !allow.split(", ").any(|s| s == method)
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"startup_catalog_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(allow));
        return response;
    }
    if crate::startup_catalog::detail::route(&path).is_some() && method != "GET" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"startup_catalog_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("GET"));
        return response;
    }
    if crate::companies::route(&path).is_some() && method != "GET" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"company_saved_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("GET"));
        return response;
    }
    if let Some(route) = crate::outreach::drafts::route(&path)
        && !route.accepts(&method)
        && !(path == crate::outreach::drafts::PATH && method == "POST")
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"outreach_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
    if crate::outreach::history::route(&path).is_some() && method != "GET" {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"outreach_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static("GET"));
        return response;
    }
    if let Some(route) = crate::contacts::enrichment::route(&path)
        && route.method() != method
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"contact_method_not_allowed"}),
        );
        response.headers_mut().insert(
            "allow",
            axum::http::HeaderValue::from_static(route.method()),
        );
        return response;
    }
    if let Some(route) = crate::contacts::route(&path)
        && !route.accepts(&method)
    {
        let mut response = reply(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"detail":"contact_method_not_allowed"}),
        );
        response
            .headers_mut()
            .insert("allow", axum::http::HeaderValue::from_static(route.allow()));
        return response;
    }
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
    if method == "PATCH" && crate::contacts::route(&path).is_some() && packet_query.is_some() {
        return fail(Failure("invalid_contact_query"));
    }
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
    let job_search = if path == crate::job_catalog::SEARCH && method == "GET" {
        match crate::job_catalog::SearchQuery::parse(request.uri().query()) {
            Ok(query) => Some(query),
            Err(error) => return fail(error),
        }
    } else {
        None
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
    if let Some(route) = crate::job_sources::owner::route(&path) {
        return job_discovery_io::dispatch(&api, route, &method, packet_query.as_deref(), &body)
            .await;
    }
    if let Some(route) = crate::startup_catalog::owner::route(&path) {
        return startup_io::dispatch(&api, route, &method, packet_query.as_deref(), &body).await;
    }
    if let Some(route) = crate::apify_metadata::owner::route(&path) {
        return apify_io::dispatch(&api, route, &method, packet_query.as_deref(), &body).await;
    }
    if let Some(route) = crate::people_research::owner::route(&path) {
        return people_research_io::dispatch(&api, route, &method, packet_query.as_deref(), &body)
            .await;
    }
    if let Some(company) = crate::contacts::enrichment::io_route(&path) {
        return contact_io::dispatch(&api, company, &method, packet_query.as_deref(), &body).await;
    }
    if let Some(action) = crate::outreach::controller::route(&path)
        && (method != "GET" || action == crate::outreach::controller::Action::Preview)
    {
        return outreach_io::dispatch(&api, action, &method, packet_query.as_deref(), &body).await;
    }
    if let Some(route) = crate::gmail_accounts::io_route(&path) {
        return gmail_accounts_io::dispatch(&api, route, &method, &body).await;
    }
    if let Some(route) = crate::gmail_legacy::io_route(&path) {
        return gmail_legacy_io::dispatch(&api, route, &method, packet_query.as_deref(), &body)
            .await;
    }
    if let Some(route) = crate::gmail_workspace::io_route(&path) {
        return gmail_workspace_io::dispatch(&api, route, &method, packet_query.as_deref(), &body)
            .await;
    }
    if let Some(route) = crate::mailboxes::routes::route(&path) {
        return accounts::dispatch(&api, route, &method, &body).await;
    }
    if let Some(crate::project_context::dashboard::Route::Build(id)) = candidate_context {
        return document_io::project_build_dispatch(&api, id, &body, packet_query.as_deref()).await;
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
    if path == "/api/v1/dashboard/runtime" {
        if method != "GET" {
            return fail(Failure("resource_read_method_not_allowed"));
        }
        if packet_query.is_some() || !body.is_empty() {
            return fail(Failure("invalid_dashboard_request"));
        }
        return reply(
            StatusCode::OK,
            json!({
                "demo_mode": false,
                "external_notifications_enabled": false,
            }),
        );
    }
    let mut state = api.connection.lock().await;
    state.revalidate().await;
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
            let route = crate::browser_profiles::route(&path).unwrap();
            let common = if matches!(route, crate::browser_profiles::Route::Native) {
                crate::owner_commands::dispatch_extension(connection, &body, &api.config).await
            } else {
                None
            };
            let outcome = match common {
                Some(result) => result,
                None => {
                    crate::browser_profiles::dispatch(
                        connection,
                        route,
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
                }
            };
            outcome.map(|data| OwnerReply {
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
        Some(connection)
            if method == "PATCH"
                && matches!(
                    crate::contacts::route(&path),
                    Some(crate::contacts::Route::Detail(_))
                ) =>
        {
            let Some(crate::contacts::Route::Detail(id)) = crate::contacts::route(&path) else {
                unreachable!()
            };
            crate::contacts::correction::correct(
                connection,
                id,
                if_match.as_deref(),
                &body,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::contacts::enrichment::route(&path).is_some() => {
            crate::contacts::enrichment::dispatch(
                connection,
                crate::contacts::enrichment::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.contact_enrichment,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::startup_catalog::search::route(&path).is_some() => {
            crate::startup_catalog::search::dispatch(
                connection,
                crate::startup_catalog::search::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::startup_catalog::shortlist::route(&path).is_some() => {
            crate::startup_catalog::shortlist::save(
                connection,
                crate::startup_catalog::shortlist::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::startup_catalog::detail::route(&path).is_some() => {
            crate::startup_catalog::detail::read(
                connection,
                crate::startup_catalog::detail::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::companies::route(&path).is_some() => crate::companies::dispatch(
            connection,
            crate::companies::route(&path).unwrap(),
            &method,
            packet_query.as_deref(),
            &body,
        )
        .await
        .map(|data| OwnerReply {
            data,
            status: StatusCode::OK,
            etag: None,
        }),
        Some(connection) if crate::contacts::route(&path).is_some() => crate::contacts::dispatch(
            connection,
            crate::contacts::route(&path).unwrap(),
            &method,
            packet_query.as_deref(),
            &body,
            &api.config.contacts,
        )
        .await
        .map(|data| OwnerReply {
            data,
            status: StatusCode::OK,
            etag: None,
        }),
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
        Some(connection) if crate::outreach::drafts::route(&path).is_some() => {
            crate::outreach::drafts::dispatch(
                connection,
                crate::outreach::drafts::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.contacts,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if crate::outreach::history::route(&path).is_some() => {
            crate::outreach::history::dispatch(
                connection,
                crate::outreach::history::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config.outreach,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
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
        Some(connection) if path == crate::conversation::preferences::PATH => {
            crate::conversation::preferences::dispatch(
                connection,
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
        Some(connection) if local_command_route.is_some() => crate::owner_commands::dispatch(
            connection,
            local_command_route.unwrap(),
            &method,
            &body,
            &api.config,
        )
        .await
        .map(|data| OwnerReply {
            data,
            status: StatusCode::OK,
            etag: None,
        }),
        Some(connection) if path == crate::connection_report::PATH => {
            crate::connection_report::dispatch(connection, &method, &body, &api.config)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if path == crate::platform_policy::PATH => {
            crate::platform_policy::dispatch(connection, &method, &body)
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
        }
        Some(connection) if platform_session_route.is_some() => crate::platform_sessions::dispatch(
            connection,
            platform_session_route.unwrap(),
            &method,
            &body,
        )
        .await
        .map(|data| OwnerReply {
            data,
            status: StatusCode::OK,
            etag: None,
        }),
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
            if matches!(
                crate::job_catalog::route(&path),
                Some(crate::job_catalog::Route::Search)
            ) && method == "GET"
            {
                crate::job_catalog::search(
                    connection,
                    job_search.as_ref().expect("parsed jobs search query"),
                    &api.config,
                )
                .await
                .map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
            } else {
                crate::job_catalog::dispatch(connection, &method, &path, &job_page)
                    .await
                    .map(|data| OwnerReply {
                        data,
                        status: StatusCode::OK,
                        etag: None,
                    })
            }
        }
        Some(connection) if crate::dashboard_legacy::route(&path).is_some() => {
            crate::dashboard_legacy::dispatch(
                connection,
                crate::dashboard_legacy::route(&path).unwrap(),
                &method,
                packet_query.as_deref(),
                &body,
                &api.config,
            )
            .await
            .map(|data| OwnerReply {
                data,
                status: StatusCode::OK,
                etag: None,
            })
        }
        Some(connection) if candidate_context.is_some() => {
            crate::project_context::dashboard::dispatch(
                connection,
                candidate_context.unwrap(),
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
        Some(connection) if path == "/api/v1/dashboard/overview" => {
            if method != "GET" {
                Err(Failure("resource_read_method_not_allowed"))
            } else if packet_query.is_some() || !body.is_empty() {
                Err(Failure("invalid_dashboard_request"))
            } else {
                dashboard_overview(connection).await.map(|data| OwnerReply {
                    data,
                    status: StatusCode::OK,
                    etag: None,
                })
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
        && recovery::alive(connection).await.is_err()
    {
        result = Err(Failure("profile_database_error"));
    }
    state.last_used = tokio::time::Instant::now();
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

async fn dashboard_overview(connection: &mut PgConnection) -> Result<Value> {
    let db = |_| Failure("profile_database_error");
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let result: Value = sqlx::query_scalar(
        "SELECT jsonb_build_object(
            'startups_discovered', (SELECT count(*) FROM companies),
            'saved_jobs', (SELECT count(*) FROM jobs),
            'relevant_jobs', (SELECT count(*) FROM jobs WHERE match_score >= 70),
            'not_yet_applied', (
                SELECT count(*) FROM jobs j
                WHERE j.status <> 'applied'
                  AND NOT EXISTS (
                      SELECT 1 FROM application_packets p
                      WHERE p.job_id = j.id
                        AND p.lifecycle_state IN ('user_reported_submitted', 'provider_confirmed_submitted')
                  )
            ),
            'shortlisted', (SELECT count(*) FROM startup_shortlist_entries),
            'applications_prepared', (SELECT count(*) FROM application_packets),
            'applications_reported_submitted', (
                SELECT count(*) FROM application_packets
                WHERE lifecycle_state = 'user_reported_submitted'
            ),
            'applications_provider_confirmed', (
                SELECT count(*) FROM application_packets
                WHERE lifecycle_state = 'provider_confirmed_submitted'
            ),
            'approved_gmail_messages', (
                SELECT count(*) FROM outreach_logs
                WHERE approval_status = 'approved'
            ),
            'outstanding_reviews', (
                SELECT count(*) FROM application_packets
                WHERE lifecycle_state IN ('needs_input', 'ready_for_review', 'preparing')
            )
        )",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
