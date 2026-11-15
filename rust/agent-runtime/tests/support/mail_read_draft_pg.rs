#[derive(Default)]
struct MailboxHttpState {
    posts: std::sync::atomic::AtomicUsize,
    requests: std::sync::Mutex<Vec<String>>,
    saved: std::sync::Mutex<Option<Value>>,
    fail_post: std::sync::atomic::AtomicBool,
    fail_get: std::sync::atomic::AtomicBool,
    reconcile_empty: std::sync::atomic::AtomicBool,
    edited: std::sync::atomic::AtomicBool,
    sent: std::sync::atomic::AtomicBool,
    wrong_inbox: std::sync::atomic::AtomicBool,
    hold_body: std::sync::atomic::AtomicBool,
    hold_post: std::sync::atomic::AtomicBool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
async fn mailbox_data_http() -> (
    String,
    Arc<MailboxHttpState>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    use axum::{
        extract::{Request, State},
        response::IntoResponse,
    };
    use base64::Engine;
    use std::sync::atomic::Ordering::SeqCst;
    async fn handle(
        State(state): State<Arc<MailboxHttpState>>,
        request: Request,
    ) -> axum::response::Response {
        let method = request.method().to_string();
        let path = request.uri().path().to_string();
        let query = request.uri().query().unwrap_or("");
        state
            .requests
            .lock()
            .unwrap()
            .push(format!("{method} {path}"));
        assert_eq!(
            request.headers()["authorization"],
            "Bearer fictional-saved-access"
        );
        let parameters = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
            .unwrap()
            .query_pairs()
            .into_owned()
            .collect::<BTreeMap<_, _>>();
        let data = match (method.as_str(), path.as_str()) {
            ("POST", "/drafts") => {
                state.posts.fetch_add(1, SeqCst);
                let bytes = axum::body::to_bytes(request.into_body(), 120000)
                    .await
                    .unwrap();
                let input: Value = serde_json::from_slice(&bytes).unwrap();
                let raw = base64::engine::general_purpose::URL_SAFE
                    .decode(input["message"]["raw"].as_str().unwrap())
                    .unwrap();
                let message = mail_parser::MessageParser::default().parse(&raw).unwrap();
                assert!(message.bcc().is_none());
                assert!(message.cc().is_none());
                let payload = json!({"id":"fictional-gmail-message","labelIds":["DRAFT"],"payload":{"mimeType":"text/plain","headers":message.headers_raw().map(|(name,value)|json!({"name":name,"value":value.trim()})).collect::<Vec<_>>(),"body":{"data":automated_apply_agents::mail_evidence::encoded(message.body_text(0).unwrap().as_bytes())}}});
                *state.saved.lock().unwrap() = Some(payload);
                if state.hold_post.load(SeqCst) {
                    state.entered.notify_one();
                    state.release.notified().await;
                }
                if state.fail_post.load(SeqCst) {
                    return axum::http::StatusCode::SERVICE_UNAVAILABLE.into_response();
                }
                json!({"id":"fictional-draft-1"})
            }
            ("GET", "/drafts") => {
                let saved = state.saved.lock().unwrap();
                if saved.is_some() && !state.reconcile_empty.load(SeqCst) {
                    json!({"drafts":[{"id":"fictional-draft-1"}]})
                } else {
                    json!({"drafts":[]})
                }
            }
            ("GET", "/drafts/fictional-draft-1") => {
                if state.fail_get.load(SeqCst) {
                    return axum::http::StatusCode::SERVICE_UNAVAILABLE.into_response();
                }
                let mut message = state.saved.lock().unwrap().clone().unwrap();
                if state.edited.load(SeqCst) {
                    message["payload"]["body"]["data"] = json!(
                        automated_apply_agents::mail_evidence::encoded(b"changed message content")
                    );
                }
                json!({"id":"fictional-draft-1","message":message})
            }
            ("GET", "/messages") => {
                if parameters
                    .get("labelIds")
                    .is_some_and(|label| label == "SENT")
                {
                    assert!(parameters["q"].starts_with("rfc822msgid:"));
                    if state.sent.load(SeqCst) {
                        json!({"messages":[{"id":"fictional-sent"}]})
                    } else {
                        json!({})
                    }
                } else {
                    assert_eq!(parameters["labelIds"], "INBOX");
                    assert!(parameters["maxResults"].parse::<i32>().unwrap() <= 5);
                    json!({"messages":[{"id":"fictional-inbox-1"}]})
                }
            }
            ("GET", "/messages/fictional-inbox-1") => {
                let mut payload = json!({"mimeType":"text/plain","headers":[{"name":"From","value":"alerts@naukri.com"},{"name":"Subject","value":"Fictional job alert"}]});
                if parameters
                    .get("format")
                    .is_some_and(|format| format == "full")
                {
                    if state.hold_body.load(SeqCst) {
                        state.entered.notify_one();
                        state.release.notified().await;
                    }
                    payload["body"] = json!({"data":automated_apply_agents::mail_evidence::encoded(b"fictional-private-body-canary job alert https://example.com/jobs/1?private=discard")});
                }
                json!({"id":"fictional-inbox-1","labelIds":if state.wrong_inbox.load(SeqCst){json!(["TRASH"])}else{json!(["INBOX"])},"payload":payload})
            }
            _ => return axum::http::StatusCode::NOT_FOUND.into_response(),
        };
        axum::Json(data).into_response()
    }
    let state = Arc::new(MailboxHttpState::default());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(handle)
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    (url, state, stop, task)
}
fn mailbox_data_settings(endpoint: &str) -> mailboxes::Settings {
    let mut values = mailbox_values();
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint.into());
    values.insert("GMAIL_READ_BODY_REVIEWED".into(), "true".into());
    values.insert("GMAIL_DRAFTS_ENABLED".into(), "true".into());
    mailboxes::Settings::from_values(&values, true).unwrap()
}
fn mailbox_reviewed(request: Uuid) -> mailboxes::ReviewedDraft {
    let recipient = "target@example.com";
    let subject = "Reviewed résumé 工作";
    let body = "Fictional owner draft body - never store raw text";
    mailboxes::ReviewedDraft::parse(json!({"expected_generation":1,"request_id":request,"recipient":recipient,"subject":subject,"body":body,"owner_reviewed":true,"content_hash":mailboxes::draft_hash(recipient,subject,body)})).unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_search_and_recent_body_review_use_real_get_transport_without_body_at_rest() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        svc.read(&mut c, Slot::One, "fictional-inbox-1").await.err(),
        Some(Failure("gmail_recent_inbox_selection_required"))
    );
    assert!(state.requests.lock().unwrap().is_empty());
    let found = svc
        .search(
            &mut c,
            Slot::One,
            mailboxes::Search::parse(json!({"query":"fictional","limit":1})).unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(found["messages"][0]["id"], "fictional-inbox-1");
    let read = svc
        .read(&mut c, Slot::One, "fictional-inbox-1")
        .await
        .unwrap();
    assert_eq!(read["body_stored"], false);
    assert_eq!(read["submission_confirmed"], false);
    assert_eq!(read["origin"]["authenticated_origin_verified"], false);
    assert_eq!(
        read["parsing"]["links"],
        json!(["https://example.com/jobs/1"])
    );
    let saved = sqlx::query_scalar::<_, Value>("SELECT value FROM owner_preferences")
        .fetch_all(&mut c)
        .await
        .unwrap();
    let text = json!(saved).to_string();
    assert!(!text.contains("fictional-private-body-canary"));
    assert!(!text.contains("Fictional job alert"));
    state
        .wrong_inbox
        .store(true, std::sync::atomic::Ordering::SeqCst);
    assert_eq!(
        svc.read(&mut c, Slot::One, "fictional-inbox-1").await.err(),
        Some(Failure("gmail_message_selection_changed"))
    );
    assert!(
        state
            .requests
            .lock()
            .unwrap()
            .iter()
            .all(|request| request.starts_with("GET "))
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_reviewed_draft_is_posted_once_verified_and_rejects_changed_content() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let id = Uuid::new_v4();
    let first = svc
        .create_draft(&mut c, Slot::One, mailbox_reviewed(id))
        .await
        .unwrap();
    assert_eq!(first["content_verified"], true);
    assert_eq!(first["sending_enabled"], false);
    svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id))
        .await
        .unwrap();
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    let mut changed = mailbox_reviewed(id);
    changed.body = "unreviewed alteration".into();
    assert_eq!(
        svc.create_draft(&mut c, Slot::One, changed).await.err(),
        Some(Failure("gmail_exact_draft_review_required"))
    );
    state
        .edited
        .store(true, std::sync::atomic::Ordering::SeqCst);
    assert_eq!(
        svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id))
            .await
            .err(),
        Some(Failure("gmail_draft_content_unverified"))
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    let rows = sqlx::query_scalar::<_, Value>(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gm54_draft:')",
    )
    .fetch_all(&mut c)
    .await
    .unwrap();
    assert_eq!(rows.len(), 1);
    assert!(!json!(rows).to_string().contains("never store raw text"));
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_ambiguous_draft_dispatch_reconciles_without_a_second_post() {
    use std::sync::atomic::Ordering::SeqCst;
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let id = Uuid::new_v4();
    state.fail_post.store(true, SeqCst);
    state.reconcile_empty.store(true, SeqCst);
    assert_eq!(
        svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id))
            .await
            .err(),
        Some(Failure("gmail_draft_request_unconfirmed"))
    );
    assert_eq!(
        svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id))
            .await
            .err(),
        Some(Failure("gmail_draft_outcome_unknown_inspect_gmail"))
    );
    assert_eq!(state.posts.load(SeqCst), 1);
    state.reconcile_empty.store(false, SeqCst);
    let result = svc
        .create_draft(&mut c, Slot::One, mailbox_reviewed(id))
        .await
        .unwrap();
    assert_eq!(result["content_verified"], true);
    assert_eq!(state.posts.load(SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_failed_readback_never_reposts_and_self_test_checks_sent_labels() {
    use std::sync::atomic::Ordering::SeqCst;
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    state.fail_get.store(true, SeqCst);
    assert_eq!(
        svc.self_test_draft(&mut c, Slot::One, 1).await.err(),
        Some(Failure("gmail_draft_read_failed"))
    );
    assert_eq!(state.posts.load(SeqCst), 1);
    state.fail_get.store(false, SeqCst);
    let receipt = svc.self_test_draft(&mut c, Slot::One, 1).await.unwrap();
    assert_eq!(receipt["sent_search_empty"], true);
    assert_eq!(receipt["sending_enabled"], false);
    assert_eq!(state.posts.load(SeqCst), 1);
    state.sent.store(true, SeqCst);
    assert_eq!(
        svc.self_test_draft(&mut c, Slot::One, 1).await.err(),
        Some(Failure("gmail_test_message_found_in_sent"))
    );
    assert_eq!(state.posts.load(SeqCst), 1);
    assert!(
        state
            .requests
            .lock()
            .unwrap()
            .iter()
            .all(|request| request == "POST /drafts" || request.starts_with("GET /"))
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_missing_consent_expired_selection_and_failed_admission_do_not_dispatch() {
    use std::sync::atomic::Ordering::SeqCst;
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let disabled = mailbox_settings();
    let disabled = Service {
        settings: &disabled,
        provider: &google,
    };
    assert_eq!(
        disabled
            .read(&mut c, Slot::One, "fictional-inbox-1")
            .await
            .err(),
        Some(Failure("gmail_body_access_review_required"))
    );
    assert_eq!(
        disabled
            .create_draft(&mut c, Slot::One, mailbox_reviewed(Uuid::new_v4()))
            .await
            .err(),
        Some(Failure("gmail_drafts_disabled"))
    );
    assert!(state.requests.lock().unwrap().is_empty());
    svc.search(
        &mut c,
        Slot::One,
        mailboxes::Search::parse(json!({"limit":1})).unwrap(),
    )
    .await
    .unwrap();
    let count = state.requests.lock().unwrap().len();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{expires_at}',to_jsonb('2020-01-01T00:00:00+00:00'::text)) WHERE starts_with(key,'gm54_selected:')").execute(&mut c).await.unwrap();
    assert_eq!(
        svc.read(&mut c, Slot::One, "fictional-inbox-1").await.err(),
        Some(Failure("gmail_recent_inbox_selection_required"))
    );
    assert_eq!(state.requests.lock().unwrap().len(), count);
    sqlx::raw_sql("CREATE FUNCTION fixture_draft_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gm54_draft:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_draft_suppress BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_draft_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(
        svc.create_draft(&mut c, Slot::One, mailbox_reviewed(Uuid::new_v4()))
            .await
            .err(),
        Some(Failure("gmail_account_write_ack_failed"))
    );
    assert_eq!(state.posts.load(SeqCst), 0);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_owner_http_search_read_drafts_and_review_validation_use_existing_gateway_contract()
 {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let mut values = host_values();
    values.extend(mailbox_values());
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint);
    values.insert("GMAIL_READ_BODY_REVIEWED".into(), "true".into());
    values.insert("GMAIL_DRAFTS_ENABLED".into(), "true".into());
    let (url, api_stop, api_task) = http_fixture_values(values).await;
    let http = client();
    let account = format!("{url}{}/1", mailboxes::routes::ACCOUNTS);
    assert_eq!(
        http.post(format!("{account}/search"))
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    for input in [
        json!({"limit":6}),
        json!({"limit":1,"send":true}),
        json!({"query":2}),
    ] {
        assert_eq!(
            http.post(format!("{account}/search"))
                .bearer_auth(HOST_TOKEN)
                .json(&input)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    let response = http
        .post(format!("{account}/search"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"query":"fictional","limit":1}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let response = http
        .post(format!("{account}/messages/fictional-inbox-1/read"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["body_stored"],
        false
    );
    let body = "Fictional owner draft body - never store raw text";
    let request = json!({"expected_generation":1,"request_id":Uuid::new_v4(),"recipient":"target@example.com","subject":"Reviewed résumé 工作","body":body,"content_hash":mailboxes::draft_hash("target@example.com","Reviewed résumé 工作",body),"owner_reviewed":true});
    let response = http
        .post(format!("{account}/drafts"))
        .bearer_auth(HOST_TOKEN)
        .json(&request)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["content_verified"],
        true
    );
    assert_eq!(
        http.get(format!("{account}/drafts"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.post(format!("{account}/send"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    api_stop.cancel();
    api_task.await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_disconnect_during_body_fetch_prevents_private_result_publication() {
    use std::sync::atomic::Ordering::SeqCst;
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let mut other = connection().await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    svc.search(
        &mut c,
        Slot::One,
        mailboxes::Search::parse(json!({"limit":1})).unwrap(),
    )
    .await
    .unwrap();
    state.hold_body.store(true, SeqCst);
    let reading = svc.read(&mut c, Slot::One, "fictional-inbox-1");
    let disconnect = async {
        state.entered.notified().await;
        svc.disconnect(&mut other, Slot::One).await.unwrap();
        state.release.notify_one();
    };
    let (read, ()) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(reading, disconnect)
    })
    .await
    .unwrap();
    assert_eq!(read.err(), Some(Failure("gmail_account_changed")));
    assert_eq!(mailbox_row(&mut c, "1").await["status"], "disconnected");
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_data_disconnect_after_post_admission_preserves_unknown_fence_without_replay() {
    use std::sync::atomic::Ordering::SeqCst;
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let mut other = connection().await;
    let (endpoint, state, stop, task) = mailbox_data_http().await;
    let settings = mailbox_data_settings(&endpoint);
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    state.hold_post.store(true, SeqCst);
    let id = Uuid::new_v4();
    let creating = svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id));
    let disconnect = async {
        state.entered.notified().await;
        svc.disconnect(&mut other, Slot::One).await.unwrap();
        state.release.notify_one();
    };
    let (created, ()) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(creating, disconnect)
    })
    .await
    .unwrap();
    assert_eq!(created.err(), Some(Failure("gmail_account_changed")));
    assert_eq!(state.posts.load(SeqCst), 1);
    let saved: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gm54_draft:')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(saved["status"], "dispatching");
    assert!(saved.get("draft_id").is_none());
    assert!(
        svc.create_draft(&mut c, Slot::One, mailbox_reviewed(id))
            .await
            .is_err()
    );
    assert_eq!(state.posts.load(SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
