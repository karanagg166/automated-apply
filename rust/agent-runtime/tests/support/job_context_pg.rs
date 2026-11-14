async fn answer_job_fixture()->(PgConnection,Uuid) {
    let mut c=knowledge_fixture().await;
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/job-context-corpus.json")).unwrap();
    let source=&corpus["listings"][1];
    let job=&source["job"];let company=&source["company"];
    let id=job["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let company_id=company["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,$2,$3,$4)").bind(company_id).bind(company["name"].as_str().unwrap()).bind(company["domain"].as_str().unwrap()).bind(&company["metadata_"]).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO jobs(id,company_id,title,description,job_url,application_url,source_platform,discovery_metadata) VALUES($1,$2,$3,$4,$5,$6,$7,$8)").bind(id).bind(company_id).bind(job["title"].as_str().unwrap()).bind(job["description"].as_str()).bind(job["job_url"].as_str().unwrap()).bind(job["application_url"].as_str()).bind(job["source_platform"].as_str().unwrap()).bind(&job["discovery_metadata"]).execute(&mut c).await.unwrap();
    (c,id)
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn answer_context_reads_bind_current_listing_and_never_mutate_owner_data() {
    use automated_apply_agents::{answer_contract,job_context::Reviewed};
    let (mut c,id)=answer_job_fixture().await;
    let before:Value=sqlx::query_scalar("SELECT jsonb_build_object('jobs',(SELECT jsonb_agg(to_jsonb(j)) FROM jobs j),'companies',(SELECT jsonb_agg(to_jsonb(c)) FROM companies c),'preferences',(SELECT jsonb_object_agg(key,value) FROM owner_preferences))").fetch_one(&mut c).await.unwrap();
    let mut tx=c.begin().await.unwrap();
    let view=Reviewed::load_in(&mut tx,id).await.unwrap().unwrap();
    assert_eq!(view.job_view()["title"],"Reviewed Role");
    let request=answer_contract::normalize(json!({"question":"Why this company?","job_id":id})).unwrap();
    let bound=view.bind_request(&request).unwrap();
    assert_eq!(bound.company_name.as_deref(),Some("Fictional Labs"));
    assert_eq!(bound.job_description.as_deref(),Some("Reviewed employer description."));
    for (company,description,error) in [(Some("Different"),None,"company_context_mismatch"),(None,Some("Original or invented description"),"job_context_mismatch")] {
        let input=answer_contract::normalize(json!({"question":"Why this company?","job_id":id,"company_name":company,"job_description":description})).unwrap();
        assert!(matches!(view.bind_request(&input),Err(Failure(code)) if code==error));
    }
    assert!(Reviewed::load_in(&mut tx,Uuid::new_v4()).await.unwrap().is_none());
    tx.commit().await.unwrap();
    let after:Value=sqlx::query_scalar("SELECT jsonb_build_object('jobs',(SELECT jsonb_agg(to_jsonb(j)) FROM jobs j),'companies',(SELECT jsonb_agg(to_jsonb(c)) FROM companies c),'preferences',(SELECT jsonb_object_agg(key,value) FROM owner_preferences))").fetch_one(&mut c).await.unwrap();
    assert_eq!(before,after);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn employer_correction_cannot_reuse_prior_company_domain_or_enrichment() {
    use automated_apply_agents::job_context::Reviewed;
    let (mut c,id)=answer_job_fixture().await;
    let mut other=connection().await;
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
    let first=Reviewed::load_in(&mut tx,id).await.unwrap().unwrap();
    assert_eq!(first.employer().unwrap()["domain"],"example.com");
    sqlx::query("UPDATE jobs SET discovery_metadata=jsonb_set(discovery_metadata,'{company_name}','\"Corrected Employer\"') WHERE id=$1").bind(id).execute(&mut other).await.unwrap();
    assert_eq!(first.digest().unwrap(),Reviewed::load_in(&mut tx,id).await.unwrap().unwrap().digest().unwrap());
    tx.commit().await.unwrap();
    let mut tx=c.begin().await.unwrap();
    let current=Reviewed::load_in(&mut tx,id).await.unwrap().unwrap();
    assert_ne!(first.digest().unwrap(),current.digest().unwrap());
    assert!(current.job_view()["company_id"].is_null());
    assert_eq!(current.employer().unwrap(),&json!({"id":null,"name":"Corrected Employer","domain":null,"metadata_":{}}));
    tx.commit().await.unwrap();
    let original:Value=sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c").fetch_one(&mut c).await.unwrap();
    assert_eq!(original["name"],"Fictional Labs");
    assert_eq!(original["domain"],"example.com");
}
