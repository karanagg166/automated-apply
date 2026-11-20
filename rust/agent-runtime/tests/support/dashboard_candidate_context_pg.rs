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

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_candidate_context_builds_local_template_and_preserves_review_history() {
    let mut database = knowledge_fixture().await;
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().canonicalize().unwrap();
    let directory = root.join("candidate_context");
    std::fs::create_dir(&directory).unwrap();
    let path = directory.join("fictional.md");
    let template = |text: &str| {
        format!(
            "---\nproject_name: Fictional Project\npersonal_contribution: >\n  {text}\nreferences: [https://example.com/fictional]\n---\n"
        )
    };
    std::fs::write(&path, template("Implemented a fictional review queue.")).unwrap();

    let mut settings = host_values();
    settings.insert("CANDIDATE_CONTEXT_ROOT".into(), root.display().to_string());
    let (url, stop, service) = http_fixture_values(settings).await;
    let http = client();
    let base = format!("{url}/api/v1/dashboard/candidate-context");
    let build = |revision: u64| {
        http.post(format!("{base}/projects/project-fictional/build"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_configuration_revision":revision}))
    };
    let configure = |revision: u64, context_file: &str| {
        http.put(format!("{base}/configuration"))
        .bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":revision,"configuration":{
             "projects":[{"id":"project-fictional","name":"Fictional Project","priority":1,"context_file":context_file}]
        }}))
    };
    assert_eq!(
        http.post(format!("{base}/projects/project-fictional/build"))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        configure(0, "candidate_context/fictional.md")
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(build(0).send().await.unwrap().status(), 409);
    let built: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(built["status"], "pending_review");
    let project = &built["project"];
    assert!(project["approved"].is_null());
    let candidate = &project["candidate"];
    let fact = &candidate["facts"][0];
    assert_eq!(fact["verification"], "owner_supplied");
    assert_eq!(fact["personal_claim"], true);
    assert_eq!(fact["text"], "Implemented a fictional review queue.");
    assert_eq!(
        fact["evidence"][0]["file"],
        "candidate_context/fictional.md"
    );
    assert_eq!(fact["evidence"][1]["url"], "https://example.com/fictional");
    let retry: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(retry, json!({"status":"unchanged","project":project}));
    let approval: Value = http.post(format!("{base}/projects/project-fictional/approve")).bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":candidate["revision"],"fact_ids":[fact["id"]],"owner_confirmed":true}))
        .send().await.unwrap().error_for_status().unwrap().json().await.unwrap();

    std::fs::write(&path, template("Revised the fictional review queue.")).unwrap();
    let rebuilt: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(rebuilt["status"], "pending_review");
    assert_ne!(
        rebuilt["project"]["candidate"]["revision"],
        candidate["revision"]
    );
    assert_eq!(rebuilt["project"]["approved"], approval);
    let answer: Value = http
        .get(format!("{base}/answer"))
        .bearer_auth(HOST_TOKEN)
        .query(&[("question", "What did you contribute?")])
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(answer["status"], "missing_approved_context");
    let stored = browser_pref(&mut database, "document_project-fictional").await;

    std::fs::write(
        &path,
        "---\nproblem_solved: &named fictional\narchitecture_hld: *named\n---\n",
    )
    .unwrap();
    let unsafe_yaml = build(1).send().await.unwrap();
    assert_eq!(unsafe_yaml.status(), 422);
    assert_eq!(
        unsafe_yaml.json::<Value>().await.unwrap()["detail"],
        "yaml_aliases_not_supported"
    );
    std::fs::write(
        &path,
        "---\nproblem_solved: Fictional with no closing delimiter\n",
    )
    .unwrap();
    assert_eq!(build(1).send().await.unwrap().status(), 422);

    let outside = root.join("outside");
    std::fs::create_dir(&outside).unwrap();
    std::fs::write(
        outside.join("project.md"),
        template("This path must stay outside the proof."),
    )
    .unwrap();
    std::os::unix::fs::symlink(&outside, directory.join("linked")).unwrap();
    assert_eq!(
        configure(1, "candidate_context/linked/project.md")
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(build(2).send().await.unwrap().status(), 422);
    assert_eq!(
        browser_pref(&mut database, "document_project-fictional").await,
        stored
    );

    std::fs::write(&path, template("A third version requiring fresh review.")).unwrap();
    assert_eq!(
        configure(2, "candidate_context/fictional.md")
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let mut holder = connection().await;
    let mut fence = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *fence)
    .await
    .unwrap();
    let blocker: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
        .fetch_one(&mut *fence)
        .await
        .unwrap();
    let request = build(3);
    let response = tokio::spawn(async move { request.send().await.unwrap() });
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let waiting: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                WHERE datname=current_database() AND application_name='automated-apply:api'
                AND $1=ANY(pg_blocking_pids(pid)))",
            )
            .bind(blocker)
            .fetch_one(&mut database)
            .await
            .unwrap();
            if waiting {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("Build reached the persistence fence");
    assert_eq!(
        http.get(format!("{url}/ready"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    sqlx::query(
        "UPDATE owner_preferences SET value=jsonb_set(value,'{revision}','4'::jsonb)
        WHERE key='candidate_configuration_v1'",
    )
    .execute(&mut *fence)
    .await
    .unwrap();
    fence.commit().await.unwrap();
    let response = response.await.unwrap();
    assert_eq!(response.status(), 409);
    assert_eq!(
        response.json::<Value>().await.unwrap()["detail"],
        "configuration_changed_reload"
    );
    assert_eq!(
        browser_pref(&mut database, "document_project-fictional").await,
        stored
    );
    stop.cancel();
    service.await.unwrap();
}

fn project_fixture_git(root: &std::path::Path, args: &[&str]) -> String {
    let result = std::process::Command::new("/usr/bin/git")
        .current_dir(root)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .args([
            "-c",
            "user.name=Fictional Owner",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
        ])
        .args(args)
        .output()
        .unwrap();
    assert!(result.status.success(), "disposable git fixture: {args:?}");
    String::from_utf8(result.stdout).unwrap().trim().to_owned()
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_candidate_context_builds_pinned_local_git_and_skips_unrelated_commits() {
    let mut database = knowledge_fixture().await;
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().canonicalize().unwrap();
    project_fixture_git(&root, &["init", "--object-format=sha1", "-b", "fictional"]);
    project_fixture_git(
        &root,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/fictional/evidence.git",
        ],
    );
    std::fs::create_dir(root.join("src")).unwrap();
    std::fs::write(root.join("src/app.tsx"), "import React from 'react';\n").unwrap();
    std::fs::write(
        root.join("pyproject.toml"),
        "[project]\ndependencies=['fastapi>=1']\n",
    )
    .unwrap();
    std::fs::write(
        root.join("README.md"),
        "# Fictional project\nFictional overview requiring review.\n",
    )
    .unwrap();
    std::fs::write(
        root.join(".env"),
        "FICTIONAL_EXCLUDED_MARKER=not_evidence\n",
    )
    .unwrap();
    project_fixture_git(&root, &["add", "."]);
    project_fixture_git(&root, &["commit", "-m", "Fictional evidence"]);
    let commit = project_fixture_git(&root, &["rev-parse", "HEAD"]);
    std::fs::write(root.join("src/app.tsx"), "import Redis from 'redis';\n").unwrap();

    let mut settings = host_values();
    settings.insert(
        "CANDIDATE_PROJECT_CHECKOUTS".into(),
        json!({"https://github.com/fictional/evidence":root}).to_string(),
    );
    let (url, stop, service) = http_fixture_values(settings).await;
    let http = client();
    let base = format!("{url}/api/v1/dashboard/candidate-context");
    let build = |revision| {
        http.post(format!("{base}/projects/project-repo/build"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_configuration_revision":revision}))
    };
    let configure = |revision, url: &str| {
        http.put(format!("{base}/configuration")).bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":revision,"configuration":{"projects":[{"id":"project-repo",
            "name":"Repo Fixture","priority":1,"repository_url":url,"tech_stack":["React","FastAPI","Redis"]}]}}))
    };
    assert_eq!(
        configure(0, "https://github.com/fictional/evidence")
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let built: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let candidate = &built["project"]["candidate"];
    assert_eq!(candidate["commit_sha"], commit);
    assert_eq!(candidate["unsupported_stack_claims"], json!(["Redis"]));
    let facts = candidate["facts"].as_array().unwrap();
    assert!(
        facts.iter().any(|fact| fact["technology"] == "FastAPI"
            && fact["evidence"][0]["file"] == "pyproject.toml")
    );
    assert!(
        facts
            .iter()
            .any(|fact| fact["technology"] == "React"
                && fact["evidence"][0]["file"] == "src/app.tsx")
    );
    assert!(facts.iter().any(
        |fact| fact["verification"] == "inferred" && fact["evidence"][0]["file"] == "README.md"
    ));
    assert!(!built.to_string().contains("FICTIONAL_EXCLUDED_MARKER"));
    assert!(facts.iter().all(|fact| fact["personal_claim"] == false));

    std::fs::write(
        root.join("unrelated.txt"),
        "Outside the selected evidence.\n",
    )
    .unwrap();
    project_fixture_git(&root, &["add", "unrelated.txt"]);
    project_fixture_git(&root, &["commit", "-m", "Unrelated fictional change"]);
    let latest = project_fixture_git(&root, &["rev-parse", "HEAD"]);
    let unchanged: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(unchanged["status"], "unchanged");
    assert_eq!(unchanged["project"]["candidate"], *candidate);
    assert_eq!(unchanged["project"]["last_checked_commit"], latest);
    assert_eq!(unchanged["project"]["audits"].as_array().unwrap().len(), 1);

    project_fixture_git(&root, &["add", "src/app.tsx"]);
    project_fixture_git(&root, &["commit", "-m", "Changed fictional evidence"]);
    let changed: Value = build(1)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(changed["status"], "pending_review");
    assert_ne!(
        changed["project"]["candidate"]["revision"],
        candidate["revision"]
    );
    assert_eq!(
        changed["project"]["candidate"]["unsupported_stack_claims"],
        json!(["React"])
    );

    project_fixture_git(
        &root,
        &[
            "remote",
            "set-url",
            "origin",
            "https://github.com/other/evidence",
        ],
    );
    let mismatch = build(1).send().await.unwrap();
    assert_eq!(mismatch.status(), 409);
    assert_eq!(
        mismatch.json::<Value>().await.unwrap()["detail"],
        "repository_origin_mismatch"
    );
    assert_eq!(
        configure(1, "https://github.com/fictional/unlisted")
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let unlisted = build(2).send().await.unwrap();
    assert_eq!(unlisted.status(), 409);
    assert_eq!(
        unlisted.json::<Value>().await.unwrap()["detail"],
        "repository_not_authorized_or_unavailable"
    );
    assert_eq!(
        browser_pref(&mut database, "candidate_project-repo").await,
        changed["project"]
    );
    stop.cancel();
    service.await.unwrap();
}
