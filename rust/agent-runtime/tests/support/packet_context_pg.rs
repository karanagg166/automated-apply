async fn packet_material_fixture()->PgConnection {
    let mut c=resource_fixture().await;
    sqlx::raw_sql("ALTER TABLE jobs ADD COLUMN last_observed_at timestamptz; DROP TABLE IF EXISTS job_source_observations; CREATE TABLE job_source_observations(id uuid PRIMARY KEY,job_id uuid NOT NULL,source varchar(100) NOT NULL,original_url text NOT NULL)").execute(&mut c).await.unwrap();
    c
}
async fn seed_packet_material(c:&mut PgConnection,raw:&Value) {
    for query in ["DELETE FROM candidate_resources","DELETE FROM candidate_evidence","DELETE FROM job_source_observations","DELETE FROM jobs","DELETE FROM companies","DELETE FROM candidate_profiles","DELETE FROM owner_preferences WHERE starts_with(key,'needs_input:')"] {sqlx::query(query).execute(&mut *c).await.unwrap();}
    let profile=&raw["profile"];
    if !profile.is_null() {
        sqlx::query("INSERT INTO candidate_profiles(id,singleton_key,version,full_name,email,phone,linkedin_url,github_url,portfolio_url,personal_website,verified_experience_years,verified_skills,verified_roles,education,projects,certifications,summary,preferences,created_at,updated_at) SELECT ($1->>'id')::uuid,'primary',($1->>'version')::integer,$1->>'full_name',$1->>'email',$1->>'phone',$1->>'linkedin_url',$1->>'github_url',$1->>'portfolio_url',$1->>'personal_website',($1->>'verified_experience_years')::double precision,$1->'verified_skills',$1->'verified_roles',$1->'education',$1->'projects',$1->'certifications',$1->>'summary',$1->'preferences',($1->>'created_at')::timestamptz,($1->>'updated_at')::timestamptz").bind(profile).execute(&mut *c).await.unwrap();
    }
    if !raw["company"].is_null() {sqlx::query("INSERT INTO companies(id,name,domain,metadata) SELECT ($1->>'id')::uuid,$1->>'name',$1->>'domain',$1->'metadata_'").bind(&raw["company"]).execute(&mut *c).await.unwrap();}
    sqlx::query("INSERT INTO jobs(id,company_id,title,description,source_platform,job_url,application_url,skills_required,location,remote_type,is_remote,employment_type,experience_level,salary_min,salary_max,salary_currency,salary_period,date_posted,last_observed_at,source_verification_status,status,discovery_metadata) SELECT ($1->>'id')::uuid,($1->>'company_id')::uuid,$1->>'title',$1->>'description',$1->>'source_platform',$1->>'job_url',$1->>'application_url',ARRAY(SELECT jsonb_array_elements_text($1->'skills_required')),$1->>'location',$1->>'remote_type',($1->>'is_remote')::boolean,$1->>'employment_type',$1->>'experience_level',($1->>'salary_min')::numeric,($1->>'salary_max')::numeric,$1->>'salary_currency',$1->>'salary_period',($1->>'date_posted')::timestamptz,($1->>'last_observed_at')::timestamptz,$1->>'source_verification_status',$1->>'status',$1->'discovery_metadata'").bind(&raw["job"]).execute(&mut *c).await.unwrap();
    let job=raw["job"]["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    if !profile.is_null() {
        let owner=profile["id"].as_str().unwrap().parse::<Uuid>().unwrap();
        for resource in raw["resources"].as_array().unwrap() {
            sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type,updated_at) SELECT ($1->>'id')::uuid,$2,$1->>'resource_type',$1->>'label',$1->>'url',($1->>'user_confirmed')::boolean,($1->>'is_primary')::boolean,$1->>'source_type',($1->>'updated_at')::timestamptz").bind(resource).bind(owner).execute(&mut *c).await.unwrap();
        }
        for evidence in raw["evidence"].as_array().unwrap() {
            sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Fictional evidence','Body remains outside packet metadata',$3,'2026-11-15T12:00:00Z',$4::timestamptz)").bind(evidence[0].as_str().unwrap().parse::<Uuid>().unwrap()).bind(owner).bind(evidence[2].as_bool().unwrap()).bind(evidence[1].as_str().unwrap()).execute(&mut *c).await.unwrap();
        }
        for revision in raw["revisions"].as_array().unwrap() {
            sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)").bind(revision[0].as_str().unwrap()).bind(json!({"candidate_profile_id":owner,"job_id":job,"ever_approved":true,"version":revision[1],"status":revision[2],"context_digest":revision[3]})).execute(&mut *c).await.unwrap();
        }
    }
    for observation in raw["observations"].as_array().unwrap() {
        sqlx::query("INSERT INTO job_source_observations(id,job_id,source,original_url) VALUES($1,$2,$3,$4)").bind(Uuid::new_v4()).bind(job).bind(observation[0].as_str().unwrap()).bind(observation[1].as_str().unwrap()).execute(&mut *c).await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_material_loader_matches_original_recipe_with_decimal_and_timestamp_fidelity() {
    use automated_apply_agents::packet_context;
    let mut c=packet_material_fixture().await;
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/packet-context-corpus.json")).unwrap();
    let now=chrono::DateTime::parse_from_rfc3339(corpus["now"].as_str().unwrap()).unwrap().with_timezone(&chrono::Utc);
    for (i,raw) in corpus["records"].as_array().unwrap().iter().enumerate() {
        seed_packet_material(&mut c,raw).await;
        let job=raw["job"]["id"].as_str().unwrap().parse::<Uuid>().unwrap();let selected=raw["selected"].as_str().map(|s|s.parse::<Uuid>().unwrap());
        let mut tx=c.begin().await.unwrap();
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
        // Driver-level UTC fingerprints must be independent of the JSON display session zone.
        sqlx::query("SET LOCAL TIME ZONE '+05:30'").execute(&mut *tx).await.unwrap();
        let snapshot=packet_context::load_in(&mut tx,job,selected,&Default::default(),now).await.unwrap().snapshot;
        assert_eq!(snapshot,corpus["outputs"][i],"case {i}");
        tx.commit().await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_material_loader_scopes_facts_and_keeps_concurrent_raw_edits_consistent() {
    use automated_apply_agents::packet_context;
    let mut c=packet_material_fixture().await;
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/packet-context-corpus.json")).unwrap();let raw=&corpus["records"][0];
    let now=chrono::DateTime::parse_from_rfc3339(corpus["now"].as_str().unwrap()).unwrap().with_timezone(&chrono::Utc);
    seed_packet_material(&mut c,raw).await;
    let owner=raw["profile"]["id"].as_str().unwrap().parse::<Uuid>().unwrap();let job=raw["job"]["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let foreign=Uuid::from_u128(99);let other_job=Uuid::from_u128(999);
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) VALUES($1,$2,'resume','Foreign private label','https://example.com/foreign',true,true,'user')").bind(Uuid::new_v4()).bind(foreign).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Foreign fact','Never a candidate fact',true,clock_timestamp(),clock_timestamp())").bind(Uuid::new_v4()).bind(foreign).execute(&mut c).await.unwrap();
    for (id,profile,scoped_job,ever) in [("e",foreign,Some(job),true),("f",owner,Some(other_job),true),("d",owner,Some(job),false)] {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)").bind(format!("needs_input:{}",id.repeat(32))).bind(json!({"candidate_profile_id":profile,"job_id":scoped_job,"ever_approved":ever,"version":3,"status":"approved","context_digest":"a".repeat(64)})).execute(&mut c).await.unwrap();
    }
    let mut tx=c.begin().await.unwrap();
    assert!(matches!(packet_context::load_in(&mut tx,job,None,&Default::default(),now).await,Err(Failure("packet_context_snapshot_required"))));tx.rollback().await.unwrap();
    let mut tx=c.begin().await.unwrap();sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
    let first=packet_context::load_in(&mut tx,job,None,&Default::default(),now).await.unwrap().snapshot;
    assert_eq!(first,corpus["outputs"][0]);assert!(!first.to_string().contains("Foreign private label"));
    let mut other=connection().await;
    sqlx::query("UPDATE candidate_profiles SET full_name='Corrected factual name' WHERE id=$1").bind(owner).execute(&mut other).await.unwrap();
    let pinned=packet_context::load_in(&mut tx,job,None,&Default::default(),now).await.unwrap().snapshot;assert_eq!(first,pinned);tx.commit().await.unwrap();
    let mut tx=c.begin().await.unwrap();sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();
    let fresh=packet_context::load_in(&mut tx,job,None,&Default::default(),now).await.unwrap().snapshot;
    assert_ne!(first["context_digest"],fresh["context_digest"]);assert_eq!(fresh["candidate"]["full_name"],"Corrected factual name");
    assert!(matches!(packet_context::load_in(&mut tx,other_job,None,&Default::default(),now).await,Err(Failure("packet_job_not_found"))));tx.commit().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT version FROM candidate_profiles WHERE id=$1").bind(owner).fetch_one(&mut c).await.unwrap(),4);
}
