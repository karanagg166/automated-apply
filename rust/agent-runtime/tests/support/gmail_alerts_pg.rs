// Deferred isolated fixtures. Gmail/Telegram transport and every person/job are fictional.
#[derive(Default)]
struct AlertReader {
    page: RefCell<Value>,
    records: RefCell<BTreeMap<String, Value>>,
    reads: RefCell<Vec<(String, bool)>>,
    queries: RefCell<Vec<(String, Option<String>)>>,
    fail_id: RefCell<Option<String>>,
    hold_body: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl mailboxes::alerts::Reader for AlertReader {
    async fn messages(&self, query: &str, page: Option<&str>) -> Result<Value> {
        self.queries
            .borrow_mut()
            .push((query.into(), page.map(str::to_owned)));
        Ok(self.page.borrow().clone())
    }
    async fn message(&self, id: &str, body: bool) -> Result<Value> {
        self.reads.borrow_mut().push((id.into(), body));
        if body && self.hold_body {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if self.fail_id.borrow().as_deref() == Some(id) {
            return Err(Failure("gmail_transport_or_response_error"));
        }
        let mut value = self.records.borrow()[id].clone();
        if !body {
            value["payload"].as_object_mut().unwrap().remove("body");
        }
        Ok(value)
    }
}
fn alert_message(id: &str, requisitions: &[&str]) -> Value {
    let text = format!(
        "fictional-private-alert-body-canary {}",
        requisitions
            .iter()
            .map(|req| format!(
                "https://www.naukri.com/job-listings-fictional-role-{req}?private=discard"
            ))
            .collect::<Vec<_>>()
            .join(" ")
    );
    json!({"id":id,"threadId":format!("thread-{id}"),"labelIds":["INBOX"],"payload":{"mimeType":"text/plain","headers":[{"name":"From","value":"Naukri <naukrialerts@naukri.com>"},{"name":"Subject","value":"Fictional job opportunities"},{"name":"Authentication-Results","value":"mx.google.com; dmarc=pass header.from=naukri.com; dkim=pass header.i=@naukri.com;"}],"body":{"data":automated_apply_agents::mail_evidence::encoded(text.as_bytes())}}})
}
fn alert_reader(records: Vec<Value>) -> AlertReader {
    AlertReader {
        page: RefCell::new(
            json!({"messages":records.iter().map(|v|json!({"id":v["id"]})).collect::<Vec<_>>()}),
        ),
        records: RefCell::new(
            records
                .into_iter()
                .map(|v| (v["id"].as_str().unwrap().to_owned(), v))
                .collect(),
        ),
        ..Default::default()
    }
}
fn alert_values() -> BTreeMap<String, String> {
    let mut values = mailbox_values();
    values.insert("GMAIL_READ_BODY_REVIEWED".into(), "true".into());
    values
}
fn alert_settings() -> mailboxes::Settings {
    mailboxes::Settings::from_values(&alert_values(), true).unwrap()
}
fn alert_policy(version: i64, generation: i64, enabled: bool) -> Value {
    json!({"expected_version":version,"expected_generation":generation,"enabled":enabled,"interval_seconds":900})
}
fn alert_key(req: &str) -> String {
    format!(
        "nau_alert:{}",
        Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("gmail-naukri-alert:{req}").as_bytes()
        )
    )
}
async fn alert_fixture() -> PgConnection {
    let (mut c, _) = listing_fixture().await;
    mailbox_seed(&mut c, false).await;
    browser_save(
        &mut c,
        "naukri_automation",
        json!({"state":"RUNNING","revision":3,"policy":null}),
    )
    .await;
    browser_save(&mut c, "exec_config:naukri", json!({"mode":"ON_DEMAND"})).await;
    let settings = alert_settings();
    let google = MailboxGoogle::default();
    Service {
        settings: &settings,
        provider: &google,
    }
    .configure_alerts(&mut c, Slot::One, alert_policy(0, 1, true))
    .await
    .unwrap();
    c
}
async fn alert_poll(
    c: &mut PgConnection,
    reader: &AlertReader,
    telegram: Option<&TelegramSettings>,
) -> Result<Value> {
    let settings = alert_settings();
    let google = MailboxGoogle::default();
    Service {
        settings: &settings,
        provider: &google,
    }
    .poll_alerts_with_reader(c, Slot::One, true, reader, telegram)
    .await
}
async fn alert_count(c: &mut PgConnection, prefix: &str) -> i64 {
    sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,$1)")
        .bind(prefix)
        .fetch_one(c)
        .await
        .unwrap()
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_policy_is_version_generation_and_body_consent_bound_and_status_labels_pause() {
    let mut c = alert_fixture().await;
    let settings = alert_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let before = browser_pref(&mut c, "gm54_alerts:1").await;
    for request in [alert_policy(0, 1, false), alert_policy(1, 2, false)] {
        assert!(
            svc.configure_alerts(&mut c, Slot::One, request)
                .await
                .is_err()
        );
        assert_eq!(browser_pref(&mut c, "gm54_alerts:1").await, before);
    }
    let restricted = mailbox_settings();
    assert_eq!(
        Service {
            settings: &restricted,
            provider: &google
        }
        .configure_alerts(&mut c, Slot::One, alert_policy(1, 1, false))
        .await
        .unwrap_err(),
        Failure("gmail_body_access_review_required")
    );
    let status = mailboxes::alerts::status(&mut c, Slot::One, &settings)
        .await
        .unwrap();
    assert_eq!(status["polling_allowed"], true);
    assert!(status.get("lease").is_none());
    browser_save(
        &mut c,
        "naukri_automation",
        json!({"state":"PAUSED","revision":4,"policy":null}),
    )
    .await;
    let status = mailboxes::alerts::status(&mut c, Slot::One, &settings)
        .await
        .unwrap();
    assert_eq!(status["configured_enabled"], true);
    assert_eq!(status["polling_allowed"], false);
    assert_eq!(status["sending_enabled"], false);
    let reader = alert_reader(vec![]);
    assert_eq!(
        alert_poll(&mut c, &reader, None).await.unwrap()["status"],
        "disabled_or_paused"
    );
    assert!(reader.queries.borrow().is_empty());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_authentication_precedes_body_and_retains_only_permanent_origin_receipt() {
    let mut c = alert_fixture().await;
    let mut bad = alert_message("alert-bad", &["923456789012"]);
    bad["payload"]["headers"][2]["value"] =
        json!("mx.google.com; dmarc=fail header.from=naukri.com; dkim=pass header.i=@naukri.com;");
    let reader = alert_reader(vec![bad]);
    let result = alert_poll(&mut c, &reader, None).await.unwrap();
    assert_eq!(result["rejected_origin"], 1);
    assert_eq!(*reader.reads.borrow(), vec![("alert-bad".into(), false)]);
    assert_eq!(alert_count(&mut c, "nau_alert:").await, 0);
    assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 1);
    reader.records.borrow_mut().insert(
        "alert-bad".into(),
        alert_message("alert-bad", &["923456789012"]),
    );
    assert_eq!(
        alert_poll(&mut c, &reader, None).await.unwrap()["already_processed"],
        1
    );
    assert_eq!(reader.reads.borrow().len(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_trusted_direct_links_create_review_candidates_once_without_jobs_application_or_body_at_rest()
 {
    let mut c = alert_fixture().await;
    let (settings, _) = telegram_question_binding(&mut c).await;
    let before = browser_snapshot(&mut c).await;
    let jobs: i64 = sqlx::query_scalar("SELECT count(*) FROM jobs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let reader = alert_reader(vec![alert_message(
        "alert-good",
        &["923456789012", "923456789012"],
    )]);
    let result = alert_poll(&mut c, &reader, Some(&settings)).await.unwrap();
    assert_eq!(result["authenticated"], 1);
    assert_eq!(result["candidates_added"], 1);
    assert_eq!(result["direct_links"], 1);
    assert_eq!(result["submitted"], false);
    assert_eq!(reader.reads.borrow().len(), 2);
    let candidate = browser_pref(&mut c, &alert_key("923456789012")).await;
    assert_eq!(candidate["state"], "NEEDS_INPUT");
    assert!(candidate["title"].is_null());
    assert!(candidate["employer"].is_null());
    assert!(!candidate["url"].as_str().unwrap().contains('?'));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM jobs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        jobs
    );
    let after = browser_snapshot(&mut c).await;
    for (key, value) in before.as_object().unwrap() {
        if key.starts_with("apply_work:")
            || key == "application_queue_policy"
            || key == "apply_queue"
        {
            assert_eq!(&after[key], value);
        }
    }
    assert!(
        !after
            .to_string()
            .contains("fictional-private-alert-body-canary")
    );
    assert!(!after.to_string().contains("private=discard"));
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_notifications WHERE kind='job_match'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM rust_telegram_outbox")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        alert_poll(&mut c, &reader, Some(&settings)).await.unwrap()["already_processed"],
        1
    );
    assert_eq!(reader.reads.borrow().len(), 2);
    let next = alert_reader(vec![alert_message("alert-second", &["923456789012"])]);
    assert_eq!(
        alert_poll(&mut c, &next, Some(&settings)).await.unwrap()["candidates_added"],
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM rust_telegram_outbox")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_spent_unknown_and_receipt_intents_require_history_review_without_new_application_work()
 {
    let mut c = alert_fixture().await;
    browser_save(&mut c,"apply_work:fictional-spent",json!({"requisition":"923456789012","stage":"NEEDS_INPUT","admitted_actions":[{"fingerprint":"apply:immutable-original"}]})).await;
    browser_save(
        &mut c,
        "apply_work:fictional-unknown",
        json!({"requisition":"923456789013","stage":"SUBMISSION_UNKNOWN"}),
    )
    .await;
    browser_save(
        &mut c,
        "naukri_receipt:923456789014",
        json!({"verification_method":"unknown","submitted":false}),
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    let reader = alert_reader(vec![alert_message(
        "alert-history",
        &["923456789012", "923456789013", "923456789014"],
    )]);
    alert_poll(&mut c, &reader, None).await.unwrap();
    for req in ["923456789012", "923456789013", "923456789014"] {
        let row = browser_pref(&mut c, &alert_key(req)).await;
        assert_eq!(row["state"], "HISTORY_REVIEW_REQUIRED");
        assert_eq!(row["submitted"], false);
    }
    let after = browser_snapshot(&mut c).await;
    for (key, value) in before.as_object().unwrap() {
        if key.starts_with("apply_work:") || key.starts_with("naukri_receipt:") {
            assert_eq!(&after[key], value);
        }
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_notifications WHERE kind='job_match'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_existing_saved_and_applied_jobs_remain_unchanged_and_are_not_new_candidates() {
    let mut c = alert_fixture().await;
    let id: Uuid = sqlx::query_scalar("SELECT id FROM jobs ORDER BY id LIMIT 1")
        .fetch_one(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE jobs SET job_url='https://www.naukri.com/job-listings-fictional-role-923456789012',source_platform='naukri',status='shortlisted' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let reader = alert_reader(vec![alert_message("alert-existing", &["923456789012"])]);
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    alert_poll(&mut c, &reader, None).await.unwrap();
    assert_eq!(
        browser_pref(&mut c, &alert_key("923456789012")).await["state"],
        "EXISTING_JOB"
    );
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        before
    );
    sqlx::query("UPDATE jobs SET status='applied' WHERE id=$1")
        .bind(id)
        .execute(&mut c)
        .await
        .unwrap();
    let reader = alert_reader(vec![alert_message("alert-applied", &["923456789012"])]);
    alert_poll(&mut c, &reader, None).await.unwrap();
    assert_eq!(
        browser_pref(&mut c, &alert_key("923456789012")).await["state"],
        "ALREADY_APPLIED"
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_changed_authority_during_body_read_blocks_publication_and_holds_no_owner_lock()
{
    for change in ["stop", "policy", "account", "mode"] {
        let mut c = alert_fixture().await;
        let mut other = connection().await;
        let mut reader = alert_reader(vec![alert_message("alert-held", &["923456789012"])]);
        reader.hold_body = true;
        let operation = alert_poll(&mut c, &reader, None);
        let competing = async {
            tokio::time::timeout(Duration::from_secs(10), reader.entered.notified())
                .await
                .expect("fixture transport did not reach the body read");
            let mut tx = other.begin().await.unwrap();
            sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *tx).await.unwrap();
            tx.commit().await.unwrap();
            match change {
                "stop" => {
                    browser_save(
                        &mut other,
                        "naukri_automation",
                        json!({"state":"STOPPED","revision":4,"policy":null}),
                    )
                    .await
                }
                "policy" => {
                    let settings = alert_settings();
                    let google = MailboxGoogle::default();
                    Service {
                        settings: &settings,
                        provider: &google,
                    }
                    .configure_alerts(&mut other, Slot::One, alert_policy(1, 1, false))
                    .await
                    .unwrap();
                }
                "account" => {
                    let settings = alert_settings();
                    let google = MailboxGoogle::default();
                    Service {
                        settings: &settings,
                        provider: &google,
                    }
                    .disconnect(&mut other, Slot::One)
                    .await
                    .unwrap();
                }
                _ => browser_save(&mut other, "exec_config:naukri", json!({"mode":"OFF"})).await,
            };
            reader.release.notify_one();
        };
        let (result, ()) = tokio::join!(operation, competing);
        assert!(result.is_err(), "{change}");
        assert_eq!(alert_count(&mut c, "nau_alert:").await, 0);
        assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 0);
        assert!(browser_pref(&mut c, "gm54_alerts:1").await["lease"].is_null());
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_partial_batch_retains_committed_receipts_but_not_cursor_and_retries_only_unread_messages()
 {
    let mut c = alert_fixture().await;
    let reader = alert_reader(vec![
        alert_message("alert-first", &["923456789012"]),
        alert_message("alert-fails", &["923456789013"]),
    ]);
    *reader.fail_id.borrow_mut() = Some("alert-fails".into());
    assert!(alert_poll(&mut c, &reader, None).await.is_err());
    assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 1);
    assert_eq!(alert_count(&mut c, "nau_alert:").await, 1);
    let policy = browser_pref(&mut c, "gm54_alerts:1").await;
    assert!(policy["watermark"].is_null());
    assert!(policy["page_token"].is_null());
    assert_eq!(policy["last_failure"]["stage"], "message_metadata");
    *reader.fail_id.borrow_mut() = None;
    let result = alert_poll(&mut c, &reader, None).await.unwrap();
    assert_eq!(result["already_processed"], 1);
    assert_eq!(result["candidates_added"], 1);
    assert_eq!(
        reader
            .reads
            .borrow()
            .iter()
            .filter(|(id, _)| id == "alert-first")
            .count(),
        2
    );
    assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 2);
    assert!(browser_pref(&mut c, "gm54_alerts:1").await["watermark"].is_i64());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_lost_future_lease_is_not_reclaimed_before_expiry_and_due_hint_is_read_only() {
    let mut c = alert_fixture().await;
    let settings = alert_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let mut reader = alert_reader(vec![alert_message("alert-lost", &["923456789012"])]);
    reader.hold_body = true;
    {
        let operation = svc.poll_alerts_with_reader(&mut c, Slot::One, true, &reader, None);
        tokio::pin!(operation);
        tokio::select! {result=&mut operation=>panic!("unexpected completion {result:?}"),_=reader.entered.notified()=>{}}
    }
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        mailboxes::alerts::due(&mut c, &settings).await.unwrap(),
        None
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(
        alert_poll(&mut c, &alert_reader(vec![]), None)
            .await
            .unwrap()["status"],
        "leased"
    );
    let mut policy = browser_pref(&mut c, "gm54_alerts:1").await;
    policy["lease_until"] = json!("2000-01-01T00:00:00Z");
    policy["next_check_at"] = Value::Null;
    browser_save(&mut c, "gm54_alerts:1", policy).await;
    assert_eq!(
        mailboxes::alerts::due(&mut c, &settings).await.unwrap(),
        Some(Slot::One)
    );
    assert_eq!(
        alert_poll(&mut c, &alert_reader(vec![]), None)
            .await
            .unwrap()["status"],
        "observed"
    );
    assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_dropped_candidate_receipt_or_notice_ack_rolls_back_that_message() {
    for prefix in ["nau_alert:", "gm54_alertmsg:", "notice"] {
        let mut c = alert_fixture().await;
        let statement = if prefix == "notice" {
            "CREATE FUNCTION fixture_alert_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER fixture_alert_drop BEFORE INSERT ON owner_notifications FOR EACH ROW EXECUTE FUNCTION fixture_alert_drop()".to_owned()
        } else {
            format!(
                "CREATE FUNCTION fixture_alert_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'{prefix}') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_alert_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_alert_drop()"
            )
        };
        sqlx::raw_sql(sqlx::AssertSqlSafe(statement))
            .execute(&mut c)
            .await
            .unwrap();
        assert_eq!(
            alert_poll(
                &mut c,
                &alert_reader(vec![alert_message("alert-drop", &["923456789012"])]),
                None
            )
            .await
            .unwrap_err(),
            Failure("gmail_alert_write_ack_failed")
        );
        assert_eq!(alert_count(&mut c, "nau_alert:").await, 0);
        assert_eq!(alert_count(&mut c, "gm54_lead:").await, 0);
        assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 0);
        assert_eq!(
            sqlx::query_scalar::<_, i64>(
                "SELECT count(*) FROM owner_notifications WHERE kind='job_match'"
            )
            .fetch_one(&mut c)
            .await
            .unwrap(),
            0
        );
        let table = if prefix == "notice" {
            "owner_notifications"
        } else {
            "owner_preferences"
        };
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
            "DROP TRIGGER fixture_alert_drop ON {table};DROP FUNCTION fixture_alert_drop()"
        )))
        .execute(&mut c)
        .await
        .unwrap();
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_oversized_pages_and_repeated_tokens_fail_closed_without_advancing_watermark() {
    let mut c = alert_fixture().await;
    let reader = alert_reader(vec![]);
    *reader.page.borrow_mut() =
        json!({"messages":(0..6).map(|n|json!({"id":format!("alert-{n}")})).collect::<Vec<_>>()});
    assert_eq!(
        alert_poll(&mut c, &reader, None).await.unwrap_err(),
        Failure("gmail_alert_page_invalid")
    );
    assert!(reader.reads.borrow().is_empty());
    *reader.page.borrow_mut() = json!({"nextPageToken":"same-token"});
    assert_eq!(
        alert_poll(&mut c, &reader, None).await.unwrap()["has_more_pages"],
        true
    );
    assert!(browser_pref(&mut c, "gm54_alerts:1").await["watermark"].is_null());
    assert_eq!(
        alert_poll(&mut c, &reader, None).await.unwrap_err(),
        Failure("gmail_alert_page_invalid")
    );
    let policy = browser_pref(&mut c, "gm54_alerts:1").await;
    assert!(policy["page_token"].is_null());
    assert!(policy["watermark"].is_null());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_http_uses_owner_auth_exact_methods_and_reports_paused_monitoring_without_provider_io()
 {
    let mut c = alert_fixture().await;
    browser_save(
        &mut c,
        "naukri_automation",
        json!({"state":"PAUSED","revision":4,"policy":null}),
    )
    .await;
    let mut values = host_values();
    values.extend(alert_values());
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let root = format!("{url}{}/1/job-alerts", mailboxes::routes::ACCOUNTS);
    assert_eq!(
        http.put(&root)
            .json(&alert_policy(1, 1, true))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.put(&root)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&alert_policy(1, 1, true))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.put(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&alert_policy(1, 1, true))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let response = http
        .post(format!("{root}/sync"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["status"],
        "disabled_or_paused"
    );
    let response: Value = http
        .get(format!("{url}{}", mailboxes::routes::ACCOUNTS))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(response["monitoring_enabled"], false);
    assert_eq!(
        response["accounts"][0]["job_alerts"]["configured_enabled"],
        true
    );
    assert_eq!(response["accounts"][0]["permissions"]["send"], false);
    stop.cancel();
    task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_cross_mailbox_requisition_dedup_retains_distinct_sources_and_current_candidate()
 {
    let mut c = alert_fixture().await;
    let first = alert_reader(vec![alert_message("alert-shared", &["923456789012"])]);
    alert_poll(&mut c, &first, None).await.unwrap();
    let store = mailbox_store();
    let mut account = mailbox_row(&mut c, "1").await;
    account["google_subject"] = json!("fictional-other-subject");
    account["account_email"] = json!("other@example.com");
    account["access"] = json!(
        store
            .encrypt(&json!("fictional-other-access"), "gm54_account:2:access")
            .unwrap()
    );
    account["refresh"] = json!(
        store
            .encrypt(&json!("fictional-other-refresh"), "gm54_account:2:refresh")
            .unwrap()
    );
    browser_save(&mut c, "gm54_account:2", account).await;
    let settings = alert_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    svc.configure_alerts(&mut c, Slot::Two, alert_policy(0, 1, true))
        .await
        .unwrap();
    let second = alert_reader(vec![alert_message("alert-shared", &["923456789012"])]);
    assert_eq!(
        svc.poll_alerts_with_reader(&mut c, Slot::Two, true, &second, None)
            .await
            .unwrap()["candidates_added"],
        0
    );
    let candidate = browser_pref(&mut c, &alert_key("923456789012")).await;
    assert_eq!(candidate["account_id"], "local:1");
    assert_eq!(
        candidate["message_references"],
        json!(["gmail:1:alert-shared", "gmail:2:alert-shared"])
    );
    let leads: Vec<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gm54_lead:')",
    )
    .fetch_all(&mut c)
    .await
    .unwrap();
    assert_eq!(leads.len(), 1);
    assert_eq!(leads[0]["sources"].as_array().unwrap().len(), 2);
    assert_eq!(alert_count(&mut c, "gm54_alertmsg:").await, 2);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_missing_thread_wrong_topic_and_indirect_links_never_create_vacancy_facts() {
    let mut c = alert_fixture().await;
    let mut missing = alert_message("alert-thread", &["923456789012"]);
    missing.as_object_mut().unwrap().remove("threadId");
    let reader = alert_reader(vec![missing]);
    assert!(alert_poll(&mut c, &reader, None).await.is_err());
    assert_eq!(reader.reads.borrow().len(), 1);
    let mut topic = alert_message("alert-topic", &["923456789012"]);
    topic["payload"]["headers"][1]["value"] = json!("Account settings changed");
    let mut links = alert_message("alert-no-links", &[]);
    links["payload"]["body"]["data"]=json!(automated_apply_agents::mail_evidence::encoded(b"https://www.naukri.com/redirect?next=https://example.com https://example.com/job-listings-fake-923456789012"));
    let reader = alert_reader(vec![topic, links]);
    let result = alert_poll(&mut c, &reader, None).await.unwrap();
    assert_eq!(result["rejected_topic"], 1);
    assert_eq!(result["without_direct_links"], 1);
    assert_eq!(alert_count(&mut c, "nau_alert:").await, 0);
    assert_eq!(alert_count(&mut c, "gm54_lead:").await, 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_paused_notifications_and_historical_unknown_telegram_deliveries_are_not_reactivated()
 {
    use sha2::Digest as _;
    let mut c = alert_fixture().await;
    let (settings, _) = telegram_question_binding(&mut c).await;
    browser_save(&mut c, "notifications", json!({"paused":true})).await;
    let req = "923456789012";
    let identity = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("gmail-naukri-alert:{req}").as_bytes(),
    );
    let hash = format!(
        "{:x}",
        sha2::Sha256::digest(format!("gmail-alert:{identity}").as_bytes())
    );
    let update = -i64::from_str_radix(&hash[..15], 16).unwrap() - (1_i64 << 60);
    sqlx::query("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'sending','Fictional uncertain historical notice')").bind(update).execute(&mut c).await.unwrap();
    alert_poll(
        &mut c,
        &alert_reader(vec![alert_message("alert-quiet", &[req])]),
        Some(&settings),
    )
    .await
    .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_notifications WHERE kind='job_match'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM rust_telegram_outbox")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT state FROM agent_telegram_deliveries WHERE update_id=$1"
        )
        .bind(update)
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "sending"
    );
}

#[derive(Default)]
struct AlertTransport {
    requests: std::sync::Mutex<Vec<String>>,
    hold_body: std::sync::atomic::AtomicBool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
async fn alert_transport() -> (
    String,
    Arc<AlertTransport>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    use axum::{
        extract::{Request, State},
        response::IntoResponse,
    };
    async fn handle(
        State(state): State<Arc<AlertTransport>>,
        request: Request,
    ) -> axum::response::Response {
        assert_eq!(request.method(), "GET");
        assert_eq!(
            request.headers()["authorization"],
            "Bearer fictional-saved-access"
        );
        let path = request.uri().path().to_owned();
        let params = reqwest::Url::parse(&format!(
            "http://127.0.0.1/?{}",
            request.uri().query().unwrap_or("")
        ))
        .unwrap()
        .query_pairs()
        .into_owned()
        .collect::<BTreeMap<_, _>>();
        state.requests.lock().unwrap().push(format!("GET {path}"));
        let value = if path == "/messages" {
            assert_eq!(params["labelIds"], "INBOX");
            assert_eq!(params["maxResults"], "5");
            assert!(params["q"].starts_with("in:inbox from:naukrialerts@naukri.com after:"));
            assert!(params["q"].contains(" before:"));
            json!({"messages":[{"id":"alert-fixed-transport"}]})
        } else if path == "/messages/alert-fixed-transport" {
            let mut message = alert_message("alert-fixed-transport", &["923456789012"]);
            if params["format"] == "metadata" {
                message["payload"].as_object_mut().unwrap().remove("body");
            } else {
                assert_eq!(params["format"], "full");
                if state.hold_body.load(std::sync::atomic::Ordering::SeqCst) {
                    state.entered.notify_one();
                    state.release.notified().await;
                }
            }
            message
        } else {
            return axum::http::StatusCode::NOT_FOUND.into_response();
        };
        axum::Json(value).into_response()
    }
    let requests = Arc::new(AlertTransport::default());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("http://{}/", listener.local_addr().unwrap());
    let router = axum::Router::new()
        .fallback(handle)
        .with_state(requests.clone());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    (endpoint, requests, stop, task)
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_fixed_get_transport_matches_owner_sync_and_never_follows_links_or_posts() {
    let mut c = alert_fixture().await;
    let (endpoint, requests, transport_stop, transport_task) = alert_transport().await;
    let mut values = host_values();
    values.extend(alert_values());
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint);
    let (url, stop, task) = http_fixture_values(values).await;
    let response = client()
        .post(format!(
            "{url}{}/1/job-alerts/sync",
            mailboxes::routes::ACCOUNTS
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["candidates_added"], 1);
    assert_eq!(result["submitted"], false);
    assert_eq!(
        *requests.requests.lock().unwrap(),
        vec![
            "GET /messages",
            "GET /messages/alert-fixed-transport",
            "GET /messages/alert-fixed-transport"
        ]
    );
    assert_eq!(
        browser_pref(&mut c, &alert_key("923456789012")).await["state"],
        "NEEDS_INPUT"
    );
    stop.cancel();
    task.await.unwrap();
    transport_stop.cancel();
    transport_task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_alert_background_worker_shares_transient_slot_and_stop_blocks_late_publication() {
    let mut observer = alert_fixture().await;
    let (endpoint, transport, transport_stop, transport_task) = alert_transport().await;
    transport
        .hold_body
        .store(true, std::sync::atomic::Ordering::SeqCst);
    let mut values = host_values();
    values.extend(alert_values());
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint);
    let config = Arc::new(Configuration::from_values(&values).unwrap());
    let control = config.connect(false).await.unwrap();
    let api = Api::new(config, control, Wake::default());
    let stop = CancellationToken::new();
    let driver = tokio::spawn(server::serve_queue_generation(api.clone(), stop.clone()));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let shutdown = stop.clone();
    let http_server = tokio::spawn(async move {
        axum::serve(
            listener,
            server::router(api).into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.cancelled_owned())
        .await
        .unwrap();
    });
    tokio::time::timeout(Duration::from_secs(8), transport.entered.notified())
        .await
        .unwrap();
    let mut lock = observer.begin().await.unwrap();
    sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *lock).await.unwrap();
    lock.commit().await.unwrap();
    let http = client();
    let root = format!("http://{address}/api/v1");
    assert_eq!(
        http.get(format!("{root}/profile"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.post(format!(
            "{root}/integrations/gmail/local/accounts/1/job-alerts/sync"
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        429
    );
    let stopped = http
        .post(format!("{root}/execution/naukri/automation/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"action":"stop","expected_revision":3}))
        .send()
        .await
        .unwrap();
    assert_eq!(stopped.status(), 200);
    transport.release.notify_one();
    let mut policy = Value::Null;
    for _ in 0..200 {
        policy = browser_pref(&mut observer, "gm54_alerts:1").await;
        if policy["error"] == "gmail_alert_cycle_failed" {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert_eq!(
        policy["last_failure"]["code"],
        "gmail_alert_authority_changed"
    );
    assert_eq!(alert_count(&mut observer, "nau_alert:").await, 0);
    assert_eq!(alert_count(&mut observer, "gm54_alertmsg:").await, 0);
    assert_eq!(
        browser_pref(&mut observer, "naukri_automation").await["state"],
        "STOPPED"
    );
    assert_eq!(transport.requests.lock().unwrap().len(), 3);
    let active:i64=sqlx::query_scalar("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='automated-apply:api'").fetch_one(&mut observer).await.unwrap();
    assert!(active <= 2);
    stop.cancel();
    assert!(
        tokio::time::timeout(Duration::from_secs(3), driver)
            .await
            .unwrap()
            .unwrap()
            .is_ok()
    );
    http_server.await.unwrap();
    transport_stop.cancel();
    transport_task.await.unwrap();
}
