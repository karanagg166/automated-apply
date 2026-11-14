#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn private_answer_fingerprints_match_original_service_expressions() {
    use automated_apply_agents::{answer_context::Stamp,answer_contract,profile_contract};
    let mut c=resource_fixture().await;
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/answer-context-corpus.json")).unwrap();
    for group in corpus["cases"].as_array().unwrap().chunks(5) {
        let first=&group[0];
        let raw=&corpus["profiles"][first["profile"].as_u64().unwrap() as usize];
        let mut storage=profile_contract::normalize_record(json!({"full_name":"Fictional Person","email":"fictional@example.com"})).unwrap();
        for (key,value) in raw.as_object().unwrap() {storage[key]=value.clone();}
        sqlx::query("UPDATE candidate_profiles SET full_name=$1->>'full_name',email=$1->>'email',phone=$1->>'phone',linkedin_url=$1->>'linkedin_url',github_url=$1->>'github_url',portfolio_url=$1->>'portfolio_url',personal_website=$1->>'personal_website',verified_experience_years=($1->>'verified_experience_years')::double precision,verified_skills=$1->'verified_skills',verified_roles=$1->'verified_roles',education=$1->'education',projects=$1->'projects',certifications=$1->'certifications',summary=$1->>'summary',preferences=$1->'preferences',version=($1->>'version')::integer WHERE singleton_key='primary'").bind(storage).execute(&mut c).await.unwrap();
        sqlx::query("DELETE FROM candidate_evidence").execute(&mut c).await.unwrap();
        for e in corpus["evidence"][first["evidence"].as_u64().unwrap() as usize].as_array().unwrap() {
            sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,project,created_at,updated_at) VALUES($1,$2,'other',$3,$4,$5,$6,'2026-11-14T00:00:00Z','2026-11-14T00:00:00Z')").bind(e["id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(e["candidate_profile_id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(e["title"].as_str().unwrap()).bind(e["content"].as_str().unwrap()).bind(e["user_confirmed"].as_bool().unwrap()).bind(&e["project"]).execute(&mut c).await.unwrap();
        }
        sqlx::query("DELETE FROM owner_preferences WHERE key='candidate_configuration_v1' OR starts_with(key,'candidate_project-') OR starts_with(key,'document_project-')").execute(&mut c).await.unwrap();
        for (key,value) in corpus["projects"][first["projects"].as_u64().unwrap() as usize].as_object().unwrap() {
            sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)").bind(key).bind(value).execute(&mut c).await.unwrap();
        }
        sqlx::query("DELETE FROM jobs").execute(&mut c).await.unwrap();
        sqlx::query("DELETE FROM companies").execute(&mut c).await.unwrap();
        let job=&corpus["jobs"][first["job"].as_u64().unwrap() as usize];
        if !job.is_null() {
            let company=&job["company"];
            if !company.is_null() {
                sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,$2,$3,$4)").bind(company["id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(company["name"].as_str().unwrap()).bind(company["domain"].as_str()).bind(&company["metadata_"]).execute(&mut c).await.unwrap();
            }
            let job=&job["job"];
            sqlx::query("INSERT INTO jobs(id,company_id,title,description,job_url,application_url,source_platform,discovery_metadata) VALUES($1,$2,$3,$4,$5,$6,$7,$8)").bind(job["id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(job["company_id"].as_str().map(|s|s.parse::<Uuid>().unwrap())).bind(job["title"].as_str().unwrap()).bind(job["description"].as_str()).bind(job["job_url"].as_str().unwrap()).bind(job["application_url"].as_str()).bind(job["source_platform"].as_str().unwrap()).bind(&job["discovery_metadata"]).execute(&mut c).await.unwrap();
        }
        for case in group {
            let request=answer_contract::normalize(case["request"].clone()).unwrap();
            let actual=Stamp::load(&mut c,&request).await.unwrap();
            assert_eq!(actual.profile_id(),profile_pin().id);
            assert_eq!(actual.profile_version(),4);
            assert_eq!(actual.generation(),case["generation"].as_str().unwrap(),"{case}");
            assert_eq!(actual.missing(),case["missing"].as_str().unwrap(),"{case}");
        }
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn answer_fingerprints_remain_consistent_during_concurrent_fact_edits() {
    use automated_apply_agents::{answer_context::Stamp,answer_contract};
    let mut c=resource_fixture().await;
    let mut other=connection().await;
    let request=answer_contract::normalize(json!({"question":"Email"})).unwrap();
    let mut tx=c.begin().await.unwrap();
    assert!(matches!(Stamp::load_in(&mut tx,&request).await,Err(Failure("answer_context_snapshot_required"))));
    tx.rollback().await.unwrap();
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
    let first=Stamp::load_in(&mut tx,&request).await.unwrap();
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Unconfirmed edit','Fictional work',false,clock_timestamp(),clock_timestamp())").bind(Uuid::new_v4()).bind(profile_pin().id).execute(&mut other).await.unwrap();
    let pinned=Stamp::load_in(&mut tx,&request).await.unwrap();
    assert_eq!(first.generation(),pinned.generation());
    tx.commit().await.unwrap();
    let current=Stamp::load(&mut c,&request).await.unwrap();
    assert_ne!(current.generation(),first.generation());
    assert_ne!(current.missing(),first.missing());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn relevant_evidence_ranks_full_owned_confirmed_inventory_before_bounding() {
    use automated_apply_agents::answer_context::relevant_evidence;
    let mut c=resource_fixture().await;
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) SELECT md5(n::text)::uuid,$1,'other','Recent irrelevant row','I built unrelated work.',true,'2026-11-14T00:00:00Z','2026-11-14T00:00:00Z' FROM generate_series(1,150) n").bind(profile_pin().id).execute(&mut c).await.unwrap();
    let wanted=Uuid::from_u128(123456);
    for (id,profile,confirmed) in [(wanted,profile_pin().id,true),(Uuid::new_v4(),profile_pin().id,false),(Uuid::new_v4(),Uuid::from_u128(99),true)] {
        sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Rust queue','I built Rust queue workers.',$3,'2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')").bind(id).bind(profile).bind(confirmed).execute(&mut c).await.unwrap();
    }
    let mut tx=c.begin().await.unwrap();
    let evidence=relevant_evidence(&mut tx,profile_pin().id,"Describe Rust queue").await.unwrap();
    assert_eq!(evidence.len(),100);
    assert_eq!(evidence[0].id,wanted);
    assert!(evidence.iter().all(|e|e.user_confirmed));
    tx.rollback().await.unwrap();
}
