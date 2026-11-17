//! Deferred native service adoption of deterministic local-answer v1, with no rewrite callback.
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn local_answer_v1_service_preserves_deterministic_provenance_draft_and_zero_provider_usage() {
    let mut c=narrative_fixture().await;
    let result=automated_apply_agents::answer_service::generate(&mut c,json!({"question":"Describe a project you built","rewrite":false,"save_draft":true}),&answer_settings()).await.unwrap();
    assert_eq!(result["source"],"deterministic_extractive");assert_eq!(result["status"],"draft_ready");assert_eq!(result["requires_review"],true);assert_eq!(result["used_llm"],false);assert!(result["provider"].is_null());assert!(result["model"].is_null());assert!(result["usage"].is_null());
    let id:Uuid=result["draft_id"].as_str().unwrap().parse().unwrap();
    let row:Value=sqlx::query_scalar("SELECT to_jsonb(d) FROM application_answer_drafts d WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();
    assert_eq!(row["review_status"],"draft");assert!(row["provider"].is_null());assert!(row["model"].is_null());assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn local_answer_v1_service_abstains_or_rejects_constraints_without_citations_or_narrative_draft() {
    let mut c=narrative_fixture().await;let before:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
    for (request,source) in [(json!({"question":"How many users does your project have?","rewrite":true,"save_draft":true}),"needs_input"),(json!({"question":"Describe a project you built","max_characters":20,"save_draft":true}),"validation_failed")] {
        let result=automated_apply_agents::answer_service::generate(&mut c,request,&answer_settings()).await.unwrap();assert_eq!(result["source"],source);assert!(result["answer"].is_null());assert_eq!(result["evidence_references"],json!([]));assert!(result["draft_id"].is_null());assert_eq!(result["used_llm"],false);
    }
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),before);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);
}
