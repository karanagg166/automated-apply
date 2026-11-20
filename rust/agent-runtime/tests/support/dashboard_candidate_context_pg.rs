#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_candidate_context_keeps_configuration_and_approval_bound() {
    let mut database = knowledge_fixture().await;
    let (url, stop, service) = http_fixture().await;
    let http = client();
    let base = format!("{url}/api/v1/dashboard/candidate-context");
    let configuration = format!("{base}/configuration");
    let project = format!("{base}/projects/project-fictional");
    let approval = format!("{project}/approve");
    let get = |path: &str| http.get(path).bearer_auth(HOST_TOKEN);
    let configure = |revision, input: &Value| {
        http.put(&configuration)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({
                "expected_revision": revision, "configuration": input,
            }))
    };
    let select = |revision: &str, ids: &[&str], confirmed| {
        http.post(&approval).bearer_auth(HOST_TOKEN).json(&json!({
            "expected_revision":revision,"fact_ids":ids,"owner_confirmed":confirmed,
        }))
    };
    let answer = |question: &str| get(&format!("{base}/answer")).query(&[("question", question)]);

    assert_eq!(http.get(&configuration).send().await.unwrap().status(), 401);
    assert_eq!(
        get(&configuration)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let wrong_method = get(&approval).send().await.unwrap();
    assert_eq!(wrong_method.status(), 405);
    assert_eq!(wrong_method.headers()["allow"], "POST");
    let defaults: Value = get(&configuration)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(defaults["revision"], 0);
    assert_eq!(
        defaults["configuration"]["projects"]
            .as_array()
            .unwrap()
            .len(),
        3
    );

    let invalid_links = json!({"links":{"github":"http://127.0.0.1/"}});
    assert_eq!(
        configure(0, &invalid_links).send().await.unwrap().status(),
        422
    );
    let deferred = json!({"resume":{"canonical_url":"https://drive.google.com/file/d/fake1234567890/view",
        "file_id":"fake1234567890","account_ref":"fictional","auto_sync_enabled":true}});
    let refused = configure(0, &deferred).send().await.unwrap();
    assert_eq!(refused.status(), 409);
    assert_eq!(
        refused.json::<Value>().await.unwrap()["detail"],
        "drive_oauth_deferred_use_manual_pdf_upload"
    );
    let input =
        json!({"projects":[{"id":"project-fictional","name":"Fictional Project","priority":1}]});
    let saved: Value = configure(0, &input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved["revision"], 1);
    assert_eq!(saved["audits"][0]["changed_fields"], json!(["projects"]));
    assert_eq!(configure(0, &input).send().await.unwrap().status(), 409);
    let repeated: Value = configure(1, &input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved, repeated);
    let listing: Value = get(&format!("{base}/projects"))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(listing[0]["project"], saved["configuration"]["projects"][0]);
    assert_eq!(listing[0]["fact_count"], 0);

    let approved_id = "a".repeat(64);
    let inferred_id = "b".repeat(64);
    let alternate_id = "c".repeat(64);
    let revision = "d".repeat(64);
    let evidence =
        json!([{"file":"candidate_context/fictional.md","content_sha256":"e".repeat(64)}]);
    let knowledge = json!({"revision":1,"candidate":{
        "configuration":listing[0]["project"], "source_hash":"f".repeat(64), "revision":revision,
        "facts":[
            {"id":approved_id,"topic":"contribution","text":"Implemented the fictional job queue.","verification":"owner_supplied","personal_claim":true,"evidence":evidence},
            {"id":inferred_id,"topic":"feature","text":"This inference must stay pending.","verification":"inferred","evidence":evidence},
            {"id":alternate_id,"topic":"overview","text":"A separate evidenced statement.","verification":"owner_supplied","evidence":evidence}
        ],"candidate_contexts":{"overview_50":"","explanation_100":"","architecture":"","technology_stack":"",
           "engineering_challenges":"","interview_explanation":"","resume_bullet_candidates":[],"fact_ids":[]}
    }});
    sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES ('document_project-fictional',$1,clock_timestamp(),clock_timestamp())")
        .bind(knowledge).execute(&mut database).await.unwrap();

    let read_back: Value = get(&project)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(read_back["candidate"]["revision"], revision);
    assert_eq!(
        answer("Explain the fictional job queue")
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap()
            .json::<Value>()
            .await
            .unwrap()["status"],
        "missing_approved_context"
    );
    assert_eq!(
        select(&revision, &[&approved_id], false)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        select(&revision, &[&inferred_id], true)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        select("old-candidate", &[&approved_id], true)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        browser_pref(&mut database, "document_project-fictional").await["revision"],
        1
    );
    let first: Value = select(&revision, &[&approved_id, &approved_id], true)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first["fact_ids"], json!([approved_id]));
    assert_eq!(
        first["contexts"]["explanation_100"],
        "Implemented the fictional job queue."
    );
    let preview: Value = answer("Explain the fictional job queue")
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(preview["status"], "draft_requires_review");
    assert_eq!(preview["text"], first["facts"][0]["text"]);
    assert_eq!(preview["sources"][0]["fact_ids"], json!([approved_id]));
    assert_eq!(
        answer("Explain")
            .query(&[("question", "duplicate")])
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let repeated: Value = select(&revision, &[&approved_id], true)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(repeated, first);

    let second: Value = select(&revision, &[&alternate_id], true)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let retained = browser_pref(&mut database, "document_project-fictional").await;
    assert_eq!(retained["revision"], 3);
    assert_eq!(retained["approved"], second);
    assert_eq!(retained["history"], json!([first]));
    assert_eq!(retained["audits"].as_array().unwrap().len(), 2);

    let renamed = json!({"projects":[{"id":"project-fictional","name":"Updated Fictional Project","priority":1}]});
    assert_eq!(configure(1, &renamed).send().await.unwrap().status(), 200);
    assert_eq!(
        select(&revision, &[&approved_id], true)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        answer("Explain the fictional job queue")
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap()
            .json::<Value>()
            .await
            .unwrap()["status"],
        "missing_approved_context"
    );
    assert_eq!(
        browser_pref(&mut database, "document_project-fictional").await,
        retained
    );
    stop.cancel();
    service.await.unwrap();
}
