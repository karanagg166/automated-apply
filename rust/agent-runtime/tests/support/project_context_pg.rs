async fn project_context_fixture() -> (PgConnection, Value) {
    let mut c = knowledge_fixture().await;
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/project-context-corpus.json")).unwrap();
    let records=corpus["records"][0].clone();
    for (key,value) in records.as_object().unwrap() {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(key).bind(value).execute(&mut c).await.unwrap();
    }
    (c, records)
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn approved_project_reads_are_scoped_read_only_and_survive_reconnect() {
    use automated_apply_agents::project_context::Snapshot;
    let (mut c, records)=project_context_fixture().await;
    // Neither unrelated private records nor the wrong project namespace are parsed.
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('document_project-01','true'),('unrelated_private_record','null')").execute(&mut c).await.unwrap();
    let before:Value=sqlx::query_scalar("SELECT jsonb_object_agg(key,value) FROM owner_preferences").fetch_one(&mut c).await.unwrap();
    let expected=Snapshot::from_records(records.as_object().unwrap()).unwrap();
    let actual=Snapshot::load(&mut c).await.unwrap();
    assert_eq!(actual.digest(),expected.digest());
    assert_eq!(actual.answer_evidence("Describe Queue","project_explanation").unwrap(),expected.answer_evidence("Describe Queue","project_explanation").unwrap());
    let prompt=actual.prompt_evidence("Describe Queue","project_explanation").unwrap();
    let encoded=serde_json::to_string(&prompt).unwrap();
    for private_metadata in ["https://","worker.rs","content_sha256","commit_sha","owner_ref","approved_at"] { assert!(!encoded.contains(private_metadata)); }
    assert!(encoded.contains("I built Queue workers"));
    drop(c);
    let mut c=connection().await;
    assert_eq!(Snapshot::load(&mut c).await.unwrap().digest(),expected.digest());
    let after:Value=sqlx::query_scalar("SELECT jsonb_object_agg(key,value) FROM owner_preferences").fetch_one(&mut c).await.unwrap();
    assert_eq!(before,after);
    // URL-only provenance changes invalidate the local digest, even though prompt text is equal.
    let mut changed=records.clone();
    changed["candidate_project-01"]["approved"]["facts"][0]["evidence"][0]["url"]=json!("https://example.com/source");
    let changed=Snapshot::from_records(changed.as_object().unwrap()).unwrap();
    assert_ne!(changed.digest(),expected.digest());
    assert_eq!(changed.prompt_evidence("Describe Queue","project_explanation").unwrap(),prompt);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn approved_projects_never_mix_concurrent_configuration_and_approval_versions() {
    use automated_apply_agents::project_context::Snapshot;
    let (mut c, _)=project_context_fixture().await;
    let mut other=connection().await;
    let mut tx=c.begin().await.unwrap();
    assert!(matches!(Snapshot::load_in(&mut tx).await,Err(Failure("project_context_snapshot_required"))));
    tx.rollback().await.unwrap();
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
    let before=Snapshot::load_in(&mut tx).await.unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{configuration,projects,0,name}','\"Changed Queue\"') WHERE key='candidate_configuration_v1'").execute(&mut other).await.unwrap();
    let pinned=Snapshot::load_in(&mut tx).await.unwrap();
    assert_eq!(before.digest(),pinned.digest());
    assert!(!pinned.answer_evidence("Describe a project","project_explanation").unwrap().is_empty());
    tx.commit().await.unwrap();
    let fresh=Snapshot::load(&mut c).await.unwrap();
    assert_ne!(fresh.digest(),before.digest());
    assert!(fresh.answer_evidence("Describe a project","project_explanation").unwrap().is_empty());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn invalid_approved_project_records_fail_closed_and_leave_no_open_transaction() {
    use automated_apply_agents::project_context::Snapshot;
    let (mut c, mut records)=project_context_fixture().await;
    records["candidate_project-01"]["approved"]["project_id"]=json!("project-02");
    let swapped=Snapshot::from_records(records.as_object().unwrap()).unwrap();
    assert!(matches!(swapped.answer_evidence("Describe a project","project_explanation"),Err(Failure("invalid_project_context_record"))));
    sqlx::query("UPDATE owner_preferences SET value='true' WHERE key='candidate_project-01'").execute(&mut c).await.unwrap();
    assert!(matches!(Snapshot::load(&mut c).await,Err(Failure("invalid_project_context_record"))));
    // Pool/connection reuse is safe after the failed read transaction is dropped.
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT 1").fetch_one(&mut c).await.unwrap(),1);
    sqlx::query("DELETE FROM owner_preferences WHERE key='candidate_configuration_v1'").execute(&mut c).await.unwrap();
    // A malformed referenced default project is still rejected rather than silently ignored.
    assert!(Snapshot::load(&mut c).await.is_err());
    sqlx::query("DELETE FROM owner_preferences WHERE key='candidate_project-01'").execute(&mut c).await.unwrap();
    let empty=Snapshot::load(&mut c).await.unwrap();
    assert!(empty.answer_evidence("Describe a project","project_explanation").unwrap().is_empty());
}
