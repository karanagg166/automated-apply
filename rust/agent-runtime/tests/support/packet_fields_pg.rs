async fn packet_field_fixture()->(PgConnection,Uuid) {
    let mut c=missing_fixture().await;
    let job=Uuid::from_u128(500);
    sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform,status) VALUES($1,'Fictional Rust role','https://www.naukri.com/job-listings-fictional-123456789012','naukri','discovered')").bind(job).execute(&mut c).await.unwrap();
    (c,job)
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_fact_preparation_keeps_missing_questions_inside_the_callers_transaction() {
    use automated_apply_agents::{packet_contract,packet_fields};
    let (mut c,job)=packet_field_fixture().await;
    let mut observer=connection().await;
    let before_profile=profile_store::get(&mut c).await.unwrap().value;
    let before_drafts:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ").execute(&mut *tx).await.unwrap();
    let profile=profile_store::get(&mut tx).await.unwrap().value;
    let email=packet_fields::build_factual_in(&mut tx,packet_contract::question(json!({"question":"Email"})).unwrap(),job,Some(&profile),None,"packet_core",&answer_settings()).await.unwrap();
    assert_eq!(email["proposed_answer"],"private-fictional@example.com");
    assert_eq!(email["provenance"]["source"],"candidate_profile");
    assert_eq!(email["review_status"],"pending");
    let missing=packet_fields::build_factual_in(&mut tx,packet_contract::question(json!({"question":"Preferred interview time?"})).unwrap(),job,Some(&profile),None,"user_provided",&answer_settings()).await.unwrap();
    assert_eq!(missing["validation_status"],"needs_input");
    assert!(missing["provenance"]["missing_input_id"].as_str().is_some());
    let inside:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut *tx).await.unwrap();
    assert_eq!(inside,1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut observer).await.unwrap(),0);
    // A later packet/field failure rolls back the complete preparation, including its question.
    assert!(sqlx::query("SELECT 1/0").execute(&mut *tx).await.is_err());
    tx.rollback().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut observer).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut observer).await.unwrap(),before_drafts);
    assert_eq!(profile_store::get(&mut observer).await.unwrap().value,before_profile);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut observer).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_preparation_never_generates_a_narrative_or_claims_attachment_or_approval() {
    use automated_apply_agents::{packet_contract,packet_fields};
    let (mut c,job)=packet_field_fixture().await;
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ").execute(&mut *tx).await.unwrap();
    let profile=profile_store::get(&mut tx).await.unwrap().value;
    for question in ["Describe a project","experience with Rust","Introduce yourself","Why this company?","Why this startup?"] {
        let field=packet_fields::build_factual_in(&mut tx,packet_contract::question(json!({"question":question})).unwrap(),job,Some(&profile),None,"user_provided",&answer_settings()).await.unwrap();
        assert_eq!(field["validation_status"],"needs_input");assert!(field["proposed_answer"].is_null());assert!(field["provenance"]["answer_draft_id"].is_null());assert!(field["provenance"]["missing_input_id"].is_null());
        assert_eq!(field["provenance"]["resolver"],"grounded_answer_service");assert_eq!(field["requires_review"],true);
    }
    let upload=packet_fields::build_factual_in(&mut tx,packet_contract::question(json!({"question":"Upload resume"})).unwrap(),job,Some(&profile),None,"packet_core",&answer_settings()).await.unwrap();
    assert_eq!(upload["validation_status"],"file_upload_required");assert_eq!(upload["provenance"]["resolver"],"manual_upload");assert!(upload["proposed_answer"].is_null());
    tx.commit().await.unwrap();
    for (query,expected) in [("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')",0),("SELECT count(*) FROM application_answer_drafts",3),("SELECT count(*) FROM llm_monthly_usage",0),("SELECT count(*) FROM application_packets",0)] {assert_eq!(sqlx::query_scalar::<_,i64>(query).fetch_one(&mut c).await.unwrap(),expected);}
}
