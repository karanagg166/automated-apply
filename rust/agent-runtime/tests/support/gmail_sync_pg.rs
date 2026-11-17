// Deferred selected sync with fictional GETs, genuine database locks/CAS and interruption.
use base64::Engine as _;
struct SelectedReader {
    pages: RefCell<std::collections::VecDeque<Value>>,
    messages: BTreeMap<String, Value>,
    calls: RefCell<Vec<Value>>,
    fail: Cell<bool>,
    hold: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl SelectedReader {
    fn new(pages: Vec<Value>, messages: Vec<Value>) -> Self {
        Self {
            pages: RefCell::new(pages.into()),
            messages: messages
                .into_iter()
                .map(|m| (m["id"].as_str().unwrap().to_owned(), m))
                .collect(),
            calls: RefCell::new(Vec::new()),
            fail: Cell::new(false),
            hold: false,
            entered: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(),
        }
    }
}
impl automated_apply_agents::gmail_accounts::sync::Reader for SelectedReader {
    async fn messages(
        &self,
        labels: &[String],
        query: Option<&str>,
        page: Option<&str>,
    ) -> Result<Value> {
        self.calls
            .borrow_mut()
            .push(json!({"operation":"list","labels":labels,"query":query,"page":page}));
        if self.fail.get() {
            return Err(Failure("gmail_read_upstream_error"));
        }
        self.pages
            .borrow_mut()
            .pop_front()
            .ok_or(Failure("gmail_read_invalid_response"))
    }
    async fn message(&self, id: &str, body: bool) -> Result<Value> {
        self.calls
            .borrow_mut()
            .push(json!({"operation":"message","id":id,"body":body}));
        if self.hold {
            self.entered.notify_one();
            self.release.notified().await;
        }
        self.messages
            .get(id)
            .cloned()
            .ok_or(Failure("gmail_read_upstream_error"))
    }
}
fn selected_metadata(id: &str, subject: &str) -> Value {
    json!({"id":id,"threadId":format!("thread-{id}"),"internalDate":(chrono::Utc::now()-chrono::Duration::hours(12)).timestamp_millis().to_string(),"labelIds":["Label_jobs","INBOX","SENT"],"payload":{"mimeType":"text/plain","body":{"data":base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b"Application received. See https://example.com/jobs/one?private=PRIVATE_QUERY_CANARY")},"headers":[{"name":"From","value":"Fictional <fictional@example.com>"},{"name":"Subject","value":subject},{"name":"To","value":"fixture@example.com"}]}})
}
async fn selected_sync_fixture(
    body: bool,
    retention: bool,
) -> (
    PgConnection,
    Uuid,
    automated_apply_agents::gmail_accounts::Settings,
    ReadGoogle,
) {
    let (mut c, id, _) = gmail_read_oauth_fixture().await;
    let mut values = mailbox_values();
    values.insert("GMAIL_READ_SYNC_ENABLED".into(), "true".into());
    values.insert("GMAIL_READ_BODY_REVIEWED".into(), body.to_string());
    values.insert("GMAIL_RETENTION_ENABLED".into(), retention.to_string());
    let settings = automated_apply_agents::gmail_accounts::Settings::from_values(&values).unwrap();
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(
            &mut c,
            json!({"account_consent":true,"read_body":body}),
            Some(id),
            &browser,
        )
        .await
        .unwrap();
    service
        .callback(
            &mut c,
            &read_state(&start),
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None,
        )
        .await
        .unwrap();
    let mut policy = json!({"expected_version":0,"enabled":true,"label_allowlist":["Label_jobs"],"retain_metadata":retention});
    if body {
        policy["read_body"] = json!(true);
        policy["body_purpose"] = json!("Read selected fictional job messages");
    }
    gmail_read_call(
        &mut c,
        &gmail_read_path(id, "/selection"),
        None,
        policy,
        &settings,
    )
    .await
    .unwrap();
    (c, id, settings, google)
}
async fn selected_records(c: &mut PgConnection, id: Uuid) -> Vec<Value> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gmail_msg:') AND value->>'account_id'=$1 ORDER BY key").bind(id.to_string()).fetch_all(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_metadata_sync_filters_topic_deduplicates_ids_and_publishes_checkpoint_without_raw_mail()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"},{"id":"msg-one"},{"id":"personal"}]})],
        vec![
            selected_metadata("msg-one", "Application received PRIVATE_SUBJECT_CANARY"),
            selected_metadata("personal", "Personal newsletter"),
        ],
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let result = service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    assert_eq!(result["sync"]["status"], "completed");
    assert_eq!(result["sync"]["scanned"], 2);
    assert_eq!(result["sync"]["inserted"], 1);
    assert!(result["sync"]["checkpoint"].is_string());
    let records = selected_records(&mut c, id).await;
    assert_eq!(records.len(), 1);
    assert_eq!(records[0]["submission_confirmed"], false);
    assert_eq!(records[0]["status_confirmed"], false);
    assert_eq!(records[0]["links"], json!([]));
    assert_eq!(records[0]["signals"], json!([]));
    assert!(!records[0].to_string().contains("PRIVATE_SUBJECT_CANARY"));
    assert!(
        reader
            .calls
            .borrow()
            .iter()
            .filter(|c| c["operation"] == "list")
            .all(|c| c["query"].is_null())
    );
    assert_eq!(
        reader
            .calls
            .borrow()
            .iter()
            .filter(|c| c["operation"] == "message" && c["id"] == "msg-one")
            .count(),
        1
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'gmail_application:') OR starts_with(key,'apply_budget:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_body_sync_keeps_safe_links_uncertain_signals_and_context_encrypted_metadata_only()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(true, true).await;
    let reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata(
            "msg-one",
            "Application received PRIVATE_SUBJECT_CANARY",
        )],
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    let records = selected_records(&mut c, id).await;
    assert_eq!(records.len(), 1);
    assert_eq!(records[0]["links"], json!(["https://example.com/jobs/one"]));
    assert_eq!(records[0]["submission_confirmed"], false);
    assert_eq!(records[0]["body_selected"], true);
    assert!(records[0]["encrypted_metadata"].is_string());
    let encoded = records[0].to_string();
    assert!(!encoded.contains("PRIVATE_SUBJECT_CANARY"));
    assert!(!encoded.contains("PRIVATE_QUERY_CANARY"));
    assert!(!encoded.contains("Application received"));
    let raw = TokenStore::from_values(&mailbox_values())
        .unwrap()
        .unwrap()
        .decrypt(
            records[0]["encrypted_metadata"].as_str().unwrap(),
            &format!("gmail-metadata:{}", records[0]["id"].as_str().unwrap()),
        )
        .unwrap();
    let retained: Value = serde_json::from_str(raw.as_str().unwrap()).unwrap();
    assert_eq!(
        retained["subject"],
        "Application received PRIVATE_SUBJECT_CANARY"
    );
    assert!(reader.calls.borrow().iter().any(|c| c["body"] == true));
    assert!(
        reader
            .calls
            .borrow()
            .iter()
            .filter(|c| c["operation"] == "list")
            .all(|c| c["query"].as_str().unwrap().starts_with("after:"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_sync_commits_page_records_and_next_cursor_atomically_then_resumes_without_rereading_prior_messages()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let reader = SelectedReader::new(
        vec![
            json!({"messages":[{"id":"msg-one"}],"nextPageToken":"private-page-2"}),
            json!({"messages":[{"id":"msg-one"},{"id":"msg-two"}]}),
        ],
        vec![
            selected_metadata("msg-one", "Application received"),
            selected_metadata("msg-two", "Interview position"),
        ],
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let first = service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    assert_eq!(first["sync"]["status"], "partial");
    assert!(first["sync"].get("page_token").is_none());
    let state = browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await;
    assert_eq!(state["page_token"], "private-page-2");
    let second = service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    assert_eq!(second["sync"]["status"], "completed");
    assert_eq!(second["sync"]["inserted"], 1);
    assert_eq!(selected_records(&mut c, id).await.len(), 2);
    let calls = reader.calls.borrow();
    assert_eq!(
        calls
            .iter()
            .filter(|c| c["operation"] == "message" && c["id"] == "msg-one")
            .count(),
        1
    );
    let lists = calls
        .iter()
        .filter(|c| c["operation"] == "list")
        .collect::<Vec<_>>();
    assert_eq!(lists[1]["page"], "private-page-2");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_sync_new_policy_during_get_prevents_old_evidence_and_cursor_publication_without_holding_owner_lock()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let mut reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata("msg-one", "Application received")],
    );
    reader.hold = true;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let mut other = connection().await;
    let sync = service.sync_with_reader(&mut c, id, &reader);
    let change = async {
        reader.entered.notified().await;
        let mut owner = other.begin().await.unwrap();
        sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *owner).await.unwrap();
        owner.commit().await.unwrap();
        gmail_read_call(
            &mut other,
            &gmail_read_path(id, "/selection"),
            None,
            json!({"expected_version":1,"enabled":false}),
            &settings,
        )
        .await
        .unwrap();
        reader.release.notify_one();
    };
    let (result, ()) = tokio::join!(sync, change);
    assert_eq!(
        result.unwrap_err(),
        Failure("gmail_sync_account_or_selection_changed")
    );
    assert!(selected_records(&mut c, id).await.is_empty());
    let state = browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await;
    assert_eq!(state["version"], 2);
    assert_eq!(state["status"], "disabled");
    assert_eq!(state["checkpoint"], Value::Null);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_sync_disconnect_during_get_cannot_restore_purged_evidence_or_active_selection()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let mut reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata("msg-one", "Application received")],
    );
    reader.hold = true;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let mut other = connection().await;
    let sync = service.sync_with_reader(&mut c, id, &reader);
    let disconnect = async {
        reader.entered.notified().await;
        service.disconnect(&mut other, id).await.unwrap();
        reader.release.notify_one();
    };
    let (result, ()) = tokio::join!(sync, disconnect);
    assert_eq!(
        result.unwrap_err(),
        Failure("gmail_sync_account_or_selection_changed")
    );
    assert!(selected_records(&mut c, id).await.is_empty());
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "disconnected"
    );
    assert_eq!(
        browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await["status"],
        "disabled"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_sync_suppressed_evidence_ack_rolls_back_all_records_and_cursor_but_keeps_committed_lease()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let reader = SelectedReader::new(
        vec![
            json!({"messages":[{"id":"msg-one"},{"id":"msg-two"}],"nextPageToken":"private-next-page"}),
        ],
        vec![
            selected_metadata("msg-one", "Application received"),
            selected_metadata("msg-two", "Interview job"),
        ],
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    sqlx::raw_sql("CREATE FUNCTION fixture_gmail_sync_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_msg:') THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_gmail_sync_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_gmail_sync_drop()").execute(&mut c).await.unwrap();
    let result = service.sync_with_reader(&mut c, id, &reader).await;
    sqlx::raw_sql("DROP TRIGGER fixture_gmail_sync_drop ON owner_preferences; DROP FUNCTION fixture_gmail_sync_drop()").execute(&mut c).await.unwrap();
    assert_eq!(result.unwrap_err(), Failure("gmail_read_write_ack_failed"));
    assert!(selected_records(&mut c, id).await.is_empty());
    let state = browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await;
    assert_eq!(state["status"], "syncing");
    assert!(state["lease_id"].is_string());
    assert_eq!(state["page_token"], Value::Null);
    assert_eq!(state["checkpoint"], Value::Null);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_failed_read_keeps_original_checkpoint_and_can_retry_only_a_new_bounded_get_batch()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata("msg-one", "Application received")],
    );
    reader.fail.set(true);
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        service
            .sync_with_reader(&mut c, id, &reader)
            .await
            .unwrap_err(),
        Failure("gmail_read_upstream_error")
    );
    let state = browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await;
    assert_eq!(state["status"], "failed");
    assert_eq!(state["checkpoint"], Value::Null);
    assert_eq!(state["lease_id"], Value::Null);
    assert!(selected_records(&mut c, id).await.is_empty());
    reader.fail.set(false);
    assert_eq!(
        service.sync_with_reader(&mut c, id, &reader).await.unwrap()["sync"]["status"],
        "completed"
    );
    assert_eq!(selected_records(&mut c, id).await.len(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_lost_read_batch_respects_active_lease_then_repeats_only_gets_without_duplicate_evidence()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let mut reader = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata("msg-one", "Application received")],
    );
    reader.hold = true;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    {
        let sync = service.sync_with_reader(&mut c, id, &reader);
        tokio::pin!(sync);
        tokio::select! {_ = reader.entered.notified()=>{},result=&mut sync=>panic!("sync unexpectedly finished: {}",result.is_ok())};
    }
    let retry = SelectedReader::new(
        vec![json!({"messages":[{"id":"msg-one"}]})],
        vec![selected_metadata("msg-one", "Application received")],
    );
    assert_eq!(
        service
            .sync_with_reader(&mut c, id, &retry)
            .await
            .unwrap_err(),
        Failure("gmail_sync_already_running")
    );
    assert!(retry.calls.borrow().is_empty());
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_until}','\"2000-01-01T00:00:00Z\"') WHERE key=$1").bind(format!("gmail_sync:{}",id.simple())).execute(&mut c).await.unwrap();
    service.sync_with_reader(&mut c, id, &retry).await.unwrap();
    assert_eq!(selected_records(&mut c, id).await.len(), 1);
    assert_eq!(
        retry
            .calls
            .borrow()
            .iter()
            .filter(|c| c["operation"] == "message")
            .count(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_scope_selection_retention_and_deployment_gates_precede_any_message_read() {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let reader = SelectedReader::new(vec![], vec![]);
    let disabled = gmail_read_settings();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &disabled,
        provider: &google,
    };
    assert_eq!(
        service
            .sync_with_reader(&mut c, id, &reader)
            .await
            .unwrap_err(),
        Failure("gmail_read_sync_disabled")
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let key = format!("gmail_sync:{}", id.simple());
    let mut state = browser_pref(&mut c, &key).await;
    state["policy"]["retain_metadata"] = json!(true);
    browser_save(&mut c, &key, state).await;
    assert_eq!(
        service
            .sync_with_reader(&mut c, id, &reader)
            .await
            .unwrap_err(),
        Failure("gmail_local_retention_worker_required")
    );
    assert!(reader.calls.borrow().is_empty());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_historical_inbox_and_sent_progress_one_folder_per_batch_and_keep_subject_signals_uncertain()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    gmail_read_call(
        &mut c,
        &gmail_read_path(id, "/selection"),
        None,
        json!({"expected_version":1,"enabled":true,"folders":["INBOX","SENT"],"history_months":24}),
        &settings,
    )
    .await
    .unwrap();
    let reader = SelectedReader::new(
        vec![
            json!({"messages":[{"id":"inbox"}]}),
            json!({"messages":[{"id":"sent"}]}),
        ],
        vec![
            selected_metadata("inbox", "Application confirmation"),
            selected_metadata("sent", "Interview application status"),
        ],
    );
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let first = service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    assert_eq!(first["sync"]["status"], "partial");
    assert_eq!(first["sync"]["folder_index"], 1);
    assert!(first["sync"]["checkpoint"].is_null());
    let second = service.sync_with_reader(&mut c, id, &reader).await.unwrap();
    assert_eq!(second["sync"]["status"], "completed");
    assert!(second["sync"]["checkpoint"].is_string());
    let lists = reader
        .calls
        .borrow()
        .iter()
        .filter(|c| c["operation"] == "list")
        .cloned()
        .collect::<Vec<_>>();
    assert_eq!(lists[0]["labels"], json!(["INBOX"]));
    assert_eq!(lists[1]["labels"], json!(["SENT"]));
    let records = selected_records(&mut c, id).await;
    assert_eq!(records.len(), 2);
    assert!(records.iter().all(|r| r["submission_confirmed"] == false
        && r["status_confirmed"] == false
        && r["signal_basis"] == "selected_subject_keywords_uncertain"));
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_duplicate_from_metadata_or_oversized_page_cannot_save_evidence_or_skip_checkpoint()
 {
    let (mut c, id, settings, google) = selected_sync_fixture(false, false).await;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    for index in 0..2 {
        let mut message = selected_metadata("msg-one", "Application received");
        if index == 0 {
            message["payload"]["headers"]
                .as_array_mut()
                .unwrap()
                .push(json!({"name":"FROM","value":"different@example.com"}));
        }
        let page = if index == 0 {
            json!({"messages":[{"id":"msg-one"}]})
        } else {
            json!({"messages":vec![json!({"id":"msg-one"});26]})
        };
        let reader = SelectedReader::new(vec![page], vec![message]);
        let result = service
            .sync_with_reader(&mut c, id, &reader)
            .await
            .unwrap_err();
        assert_eq!(
            result,
            Failure(if index == 0 {
                "gmail_message_metadata_invalid"
            } else {
                "gmail_read_invalid_response"
            })
        );
        assert!(selected_records(&mut c, id).await.is_empty());
        let state = browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await;
        assert_eq!(state["checkpoint"], Value::Null);
        assert_eq!(state["status"], "failed");
        assert_eq!(state["lease_id"], Value::Null);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_selected_actual_http_sync_uses_only_fixed_get_list_and_metadata_endpoints() {
    use axum::{
        extract::{Request, State},
        response::IntoResponse,
    };
    let (mut c, id, _settings, google) = selected_sync_fixture(false, false).await;
    let calls = Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    async fn read(
        State(calls): State<Arc<std::sync::Mutex<Vec<String>>>>,
        request: Request,
    ) -> axum::response::Response {
        let path = request.uri().path().to_owned();
        calls
            .lock()
            .unwrap()
            .push(format!("{} {path}", request.method()));
        assert_eq!(request.method(), axum::http::Method::GET);
        assert_eq!(
            request.headers()["authorization"],
            "Bearer fictional-read-access"
        );
        let query = reqwest::Url::parse(&format!("http://127.0.0.1{}", request.uri()))
            .unwrap()
            .query_pairs()
            .into_owned()
            .collect::<BTreeMap<_, _>>();
        let value = match path.as_str() {
            "/messages" => {
                assert_eq!(query["maxResults"], "25");
                assert_eq!(query["labelIds"], "Label_jobs");
                assert!(!query.contains_key("q"));
                json!({"messages":[{"id":"msg-one"}]})
            }
            "/messages/msg-one" => {
                assert_eq!(query["format"], "metadata");
                selected_metadata("msg-one", "Application received")
            }
            _ => return axum::http::StatusCode::NOT_FOUND.into_response(),
        };
        axum::Json(value).into_response()
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("http://{}", listener.local_addr().unwrap());
    let read_stop = CancellationToken::new();
    let shutdown = read_stop.clone();
    let reader = axum::Router::new().fallback(read).with_state(calls.clone());
    let read_server = tokio::spawn(async move {
        axum::serve(listener, reader)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let mut values = browser_values();
    values.extend(mailbox_values());
    values.insert("GMAIL_READ_SYNC_ENABLED".into(), "true".into());
    values.insert("GMAIL_CLIENT_ID".into(), "fictional-client".into());
    values.insert("GMAIL_CLIENT_SECRET".into(), "fictional-secret".into());
    values.insert(
        "GMAIL_REDIRECT_URI".into(),
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback".into(),
    );
    values.insert("RUST_GOOGLE_FIXTURE_ENDPOINT".into(), endpoint.clone());
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint);
    let (url, stop, server) = http_fixture_values(values).await;
    let http = client();
    let target = format!("{url}{}", gmail_read_path(id, "/sync"));
    assert_eq!(http.post(&target).send().await.unwrap().status(), 401);
    let response = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    let code = response.status();
    let result: Value = response.json().await.unwrap();
    assert_eq!(code, 200, "{result}");
    assert_eq!(result["sync"]["status"], "completed");
    assert_eq!(result["sync"]["inserted"], 1);
    assert_eq!(google.refreshes.get(), 0);
    assert_eq!(
        calls.lock().unwrap().as_slice(),
        ["GET /messages", "GET /messages/msg-one"]
    );
    assert_eq!(selected_records(&mut c, id).await.len(), 1);
    stop.cancel();
    server.await.unwrap();
    read_stop.cancel();
    read_server.await.unwrap();
}
