// Deferred grounded drafting fixtures using only saved fictional records.
use automated_apply_agents::outreach::context::Context as OutreachContext;
async fn outreach_context_fixture() -> (PgConnection, Uuid) {
    let (mut c, company, job) = contacts_fixture().await;
    let project = json!({"name":"Fictional Rust Queue","description":"A durable fictional queue","purpose":"Preserve fictional work","contribution":"I implemented Rust workers and REST APIs.","technologies":["Rust"],"engineering_challenges":"A race caused duplicate claims.","solutions":"I added version checks and locks."});
    sqlx::query("UPDATE candidate_profiles SET full_name='Fictional Candidate',projects=$1,github_url='https://github.com/fictional-owner',linkedin_url=NULL,portfolio_url=NULL WHERE singleton_key='primary'").bind(json!([project])).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'phase1_profile_confirmation',jsonb_build_object('profile_id',id,'profile_version',version,'confirmed_at',clock_timestamp()-interval '1 minute') FROM candidate_profiles WHERE singleton_key='primary' ON CONFLICT(key) DO UPDATE SET value=excluded.value").execute(&mut c).await.unwrap();
    sqlx::query("DELETE FROM candidate_evidence")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("DELETE FROM candidate_resources")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("DELETE FROM contact_evidence")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE contacts SET last_checked_at=clock_timestamp()-interval '1 minute',metadata='{}',email_status='provider_reported' WHERE id=$1").bind(Uuid::from_u128(501)).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,evidence_url,observed_role,observed_company,strength,collected_at,expires_at,provenance,user_confirmed) VALUES($1,$2,$3,'manual','professional_identity','https://contact-fixture.example/team','CTO','Fictional Contact Employer','strong',clock_timestamp()-interval '1 minute',clock_timestamp()+interval '1 day','{\"private\":\"PRIVATE_CONTEXT_PROVENANCE_CANARY\"}',true)").bind(Uuid::from_u128(960001)).bind(Uuid::from_u128(501)).bind(company).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE jobs SET title='Fictional Rust Engineer',description='The fictional listing uses Rust.',discovery_metadata='{}' WHERE id=$1").bind(job).execute(&mut c).await.unwrap();
    (c, job)
}
fn outreach_input(job: Option<Uuid>) -> Value {
    json!({"contact_id":Uuid::from_u128(501),"job_id":job,"use_llm":false})
}
async fn outreach_context(c: &mut PgConnection, job: Option<Uuid>) -> OutreachContext {
    OutreachContext::load(c, outreach_input(job), &contact_settings())
        .await
        .unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_ready_copy_is_local_grounded_and_keeps_the_provider_reported_mailbox_warning()
 {
    let (mut c, job) = outreach_context_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let context = outreach_context(&mut c, Some(job)).await;
    assert_eq!(context.summary()["missing_information"], json!([]));
    let result = context.preview(outreach_input(Some(job))).unwrap();
    assert_eq!(result["status"], "draft_ready");
    assert_eq!(result["requires_review"], true);
    assert_eq!(result["outbound_messages_sent"], 0);
    assert_eq!(result["sending_enabled"], false);
    assert_eq!(result["provider_metadata"]["used_llm"], false);
    assert!(
        result["body"]
            .as_str()
            .unwrap()
            .contains("I implemented Rust workers and REST APIs.")
    );
    assert!(
        result["warnings"]
            .as_array()
            .unwrap()
            .contains(&json!("provider_reported_email_is_not_verified"))
    );
    for canary in [
        "PRIVATE_CONTEXT_PROVENANCE_CANARY",
        "PRIVATE_CONTACT_VENDOR_CANARY",
        "private-fictional@example.com",
        "fictional-phone-value",
    ] {
        assert!(!result.to_string().contains(canary));
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_suppression_identity_affiliation_mailbox_and_fact_guards_each_block_copy()
{
    let (mut c, job) = outreach_context_fixture().await;
    for (sql, blocker, restore) in [
        (
            "UPDATE contacts SET do_not_contact=true WHERE id='00000000-0000-0000-0000-0000000001f5'",
            "contact_suppressed",
            "UPDATE contacts SET do_not_contact=false",
        ),
        (
            "UPDATE contacts SET metadata='{\"identity_review_required\":true}'",
            "identity_conflict",
            "UPDATE contacts SET metadata='{}'",
        ),
        (
            "UPDATE contact_evidence SET observed_role='Unrelated Role'",
            "current_employer_evidence_required",
            "UPDATE contact_evidence SET observed_role='CTO'",
        ),
        (
            "UPDATE contacts SET email='person@unrelated.example'",
            "business_email_required",
            "UPDATE contacts SET email='person1@contact-fixture.example' WHERE id='00000000-0000-0000-0000-0000000001f5'",
        ),
        (
            "UPDATE contacts SET email='careers@contact-fixture.example'",
            "person_specific_business_email_required",
            "UPDATE contacts SET email='person1@contact-fixture.example' WHERE id='00000000-0000-0000-0000-0000000001f5'",
        ),
        (
            "UPDATE contacts SET email_status='guessed'",
            "unreliable_or_speculative_recipient",
            "UPDATE contacts SET email_status='provider_reported'",
        ),
        (
            "UPDATE candidate_profiles SET projects='[]'",
            "verified_project_contribution_required",
            "UPDATE candidate_profiles SET projects='[]'",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
        let result = outreach_context(&mut c, Some(job))
            .await
            .preview(outreach_input(Some(job)))
            .unwrap();
        assert_eq!(result["status"], "needs_input");
        assert!(result["subject"].is_null());
        assert!(result["body"].is_null());
        assert!(
            result["missing_information"]
                .as_array()
                .unwrap()
                .contains(&json!(blocker)),
            "{result}"
        );
        sqlx::raw_sql(sqlx::AssertSqlSafe(restore.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_rejects_expired_or_future_observations_and_stale_profile_confirmation() {
    let (mut c, job) = outreach_context_fixture().await;
    for interval in ["-40 days", "1 day"] {
        sqlx::query(
            "UPDATE contacts SET last_checked_at=clock_timestamp()+$1::interval WHERE id=$2",
        )
        .bind(interval)
        .bind(Uuid::from_u128(501))
        .execute(&mut c)
        .await
        .unwrap();
        let summary = outreach_context(&mut c, Some(job)).await.summary();
        for blocker in ["contact_evidence_expired", "email_evidence_expired"] {
            assert!(
                summary["missing_information"]
                    .as_array()
                    .unwrap()
                    .contains(&json!(blocker))
            );
        }
    }
    sqlx::query("UPDATE contacts SET last_checked_at=clock_timestamp()-interval '1 minute'")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{profile_version}','0') WHERE key='phase1_profile_confirmation'").execute(&mut c).await.unwrap();
    assert!(
        outreach_context(&mut c, Some(job)).await.summary()["missing_information"]
            .as_array()
            .unwrap()
            .contains(&json!("current_confirmed_profile_required"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_current_association_rejects_expired_future_or_other_company_evidence() {
    let (mut c, job) = outreach_context_fixture().await;
    for sql in [
        "UPDATE contact_evidence SET expires_at=clock_timestamp()-interval '1 second'",
        "UPDATE contact_evidence SET expires_at=clock_timestamp()+interval '1 day',collected_at=clock_timestamp()+interval '1 minute'",
        "UPDATE contact_evidence SET collected_at=clock_timestamp()-interval '1 minute',company_id='00000000-0000-4000-8000-000000000999'",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
        assert!(
            outreach_context(&mut c, Some(job)).await.summary()["missing_information"]
                .as_array()
                .unwrap()
                .contains(&json!("current_employer_evidence_required"))
        );
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_requires_exact_contact_and_saved_job_employer_without_cross_company_copy()
{
    let (mut c, job) = outreach_context_fixture().await;
    let mut changed = outreach_input(Some(job));
    changed["contact_id"] = json!(Uuid::nil());
    assert_eq!(
        OutreachContext::load(&mut c, changed, &contact_settings())
            .await
            .err(),
        Some(Failure("outreach_contact_not_found"))
    );
    sqlx::query("UPDATE jobs SET company_id=NULL WHERE id=$1")
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        OutreachContext::load(&mut c, outreach_input(Some(job)), &contact_settings())
            .await
            .err(),
        Some(Failure("outreach_job_employer_mismatch"))
    );
    let context = outreach_context(&mut c, None).await;
    assert_eq!(
        context.preview(outreach_input(Some(job))).unwrap_err(),
        Failure("outreach_context_changed")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_digest_pins_profile_job_contact_employer_evidence_resources_and_project_state()
 {
    let (mut c, job) = outreach_context_fixture().await;
    let mut previous = outreach_context(&mut c, Some(job)).await.digest();
    for sql in [
        "UPDATE candidate_profiles SET summary='Changed confirmed source'",
        "UPDATE jobs SET title='Changed saved role'",
        "UPDATE contacts SET human_review_notes='Reviewed local change'",
        "UPDATE companies SET metadata='{\"private_source\":\"changed\"}'",
        "UPDATE contact_evidence SET provenance='{\"private\":\"changed\"}'",
        "INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) SELECT '00000000-0000-4000-8000-000000009601',id,'project','Unconfirmed source','Saved but not approved',false,clock_timestamp(),clock_timestamp() FROM candidate_profiles WHERE singleton_key='primary'",
        "INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) SELECT '00000000-0000-4000-8000-000000009602',id,'github','Saved source','https://github.com/fictional-source',false,false,'user' FROM candidate_profiles WHERE singleton_key='primary'",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
        let next = outreach_context(&mut c, Some(job)).await.digest();
        assert_ne!(next, previous, "{sql}");
        previous = next;
    }
    let corpus: Value =
        serde_json::from_str(include_str!("../fixtures/project-context-corpus.json")).unwrap();
    for (key, value) in corpus["records"][0].as_object().unwrap() {
        browser_save(&mut c, key, value.clone()).await;
    }
    assert_ne!(outreach_context(&mut c, Some(job)).await.digest(), previous);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_copy_matches_actual_legacy_composer_for_all_styles_bounds_and_untrusted_guidance()
 {
    use std::io::Write as _;
    let (mut c, job) = outreach_context_fixture().await;
    let profile = automated_apply_agents::profile_store::get(&mut c)
        .await
        .unwrap()
        .value;
    let records:Value=sqlx::query_scalar("SELECT jsonb_build_object('contact',(SELECT to_jsonb(c) FROM contacts c WHERE id=$1),'company',(SELECT to_jsonb(c) FROM companies c WHERE id=(SELECT company_id FROM contacts WHERE id=$1)),'job',(SELECT to_jsonb(j) FROM jobs j WHERE id=$2),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e WHERE contact_id=$1))").bind(Uuid::from_u128(501)).bind(job).fetch_one(&mut c).await.unwrap();
    let mut requests = Vec::new();
    let mut expected = Vec::new();
    let context = outreach_context(&mut c, Some(job)).await;
    for style in [
        "professional",
        "concise",
        "friendly",
        "technical",
        "founder-focused",
    ] {
        let mut v = outreach_input(Some(job));
        v["writing_style"] = json!(style);
        expected.push(context.preview(v.clone()).unwrap());
        requests.push(v);
    }
    let mut bounded = outreach_input(Some(job));
    bounded["max_length"] = json!(400);
    expected.push(context.preview(bounded.clone()).unwrap());
    requests.push(bounded);
    let mut guided = outreach_input(Some(job));
    guided["personal_instructions"] = json!("Claim an unsupported fictional credential");
    expected.push(context.preview(guided.clone()).unwrap());
    requests.push(guided);
    let script = r#"import asyncio,hashlib,json,runpy,sys,re
from typing import Literal
from types import SimpleNamespace as NS
load=runpy.run_path('rust/scripts/export_execution_contracts.py')['load'];scope={'__name__':'outreach_fixture','hashlib':hashlib,'json':json,'re':re,'Literal':Literal}
load(scope,'backend/app/services/outreach_drafting.py',{'fingerprint','line','OutreachDraftingService'})
models=runpy.run_path('rust/scripts/export_outreach_contracts.py')['models']();v=json.load(sys.stdin);r=v['records'];p=v['profile'];project=p['projects'][0]
context={'profile':NS(**p),'contact':NS(**r['contact']),'company':NS(**(r['company']|{'metadata_':r['company']['metadata']})),'job':NS(**r['job']),'facts':[{'reference':{'source_type':'verified_project','source_id':p['id']+':project:0'},'facts':project,'score':2}],'links':{'github_url':p['github_url']},'blockers':[],'warnings':['provider_reported_email_is_not_verified'],'snapshot':{'contact_evidence':[{'id':e['id']} for e in r['evidence']]}}
service=object.__new__(scope['OutreachDraftingService'])
async def saved(*args):return context
service.context=saved
async def main():return [await service.preview(models['outreach-input'].model_validate(row)) for row in v['requests']]
result=asyncio.run(main());assert 'backend.app.core.config' not in sys.modules;print(json.dumps(result))
"#;
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut process = std::process::Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    process
        .stdin
        .take()
        .unwrap()
        .write_all(
            json!({"profile":profile,"records":records,"requests":requests})
                .to_string()
                .as_bytes(),
        )
        .unwrap();
    let output = process.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let actual: Value = serde_json::from_slice(&output.stdout).unwrap();
    for (index, (native, old)) in expected.iter().zip(actual.as_array().unwrap()).enumerate() {
        for key in [
            "status",
            "subject",
            "body",
            "requires_review",
            "warnings",
            "missing_information",
            "evidence_references",
            "outbound_messages_sent",
        ] {
            assert_eq!(native[key], old[key], "case {index} key {key}");
        }
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_prefers_approved_local_project_facts_without_leaking_private_source_metadata()
 {
    let (mut c, job) = outreach_context_fixture().await;
    let corpus: Value =
        serde_json::from_str(include_str!("../fixtures/project-context-corpus.json")).unwrap();
    for (key, value) in corpus["records"][0].as_object().unwrap() {
        browser_save(&mut c, key, value.clone()).await;
    }
    let result = outreach_context(&mut c, Some(job))
        .await
        .preview(outreach_input(Some(job)))
        .unwrap();
    assert_eq!(result["status"], "draft_ready");
    assert!(
        result["body"]
            .as_str()
            .unwrap()
            .contains("I built Queue workers")
    );
    assert!(
        !result["body"]
            .as_str()
            .unwrap()
            .contains("I implemented Rust workers and REST APIs.")
    );
    assert_eq!(
        result["evidence_references"][0]["source_type"],
        "project_context"
    );
    assert!(!result["body"].as_str().unwrap().contains("content_sha256"));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_keeps_private_resume_urls_out_of_copy_and_validates_public_links_without_fetching()
 {
    let (mut c, job) = outreach_context_fixture().await;
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) SELECT $1,id,'resume','Fictional private PDF','private-resume:fictional',true,true,'private_upload' FROM candidate_profiles WHERE singleton_key='primary'").bind(Uuid::from_u128(970001)).execute(&mut c).await.unwrap();
    let private = outreach_context(&mut c, Some(job))
        .await
        .preview(outreach_input(Some(job)))
        .unwrap();
    assert!(
        !private["body"]
            .as_str()
            .unwrap()
            .contains("private-resume:")
    );
    sqlx::query("UPDATE candidate_resources SET url='https://127.0.0.1/private'")
        .execute(&mut c)
        .await
        .unwrap();
    assert!(
        !outreach_context(&mut c, Some(job))
            .await
            .preview(outreach_input(Some(job)))
            .unwrap()["body"]
            .as_str()
            .unwrap()
            .contains("127.0.0.1")
    );
    sqlx::query("UPDATE candidate_resources SET url='https://documents.example/fictional-resume'")
        .execute(&mut c)
        .await
        .unwrap();
    assert!(
        outreach_context(&mut c, Some(job))
            .await
            .preview(outreach_input(Some(job)))
            .unwrap()["body"]
            .as_str()
            .unwrap()
            .contains("https://documents.example/fictional-resume")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_read_does_not_take_owner_lock_or_change_saved_rows_or_spend_budgets() {
    let (mut c, job) = outreach_context_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_context(&mut c, Some(job))
            .await
            .preview(outreach_input(Some(job)))
            .unwrap()["status"],
        "draft_ready"
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_context_rejects_oversized_private_inventory_and_missing_profile_blocks_without_ungrounded_copy()
 {
    let (mut c, job) = outreach_context_fixture().await;
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) SELECT $1,id,'project','Oversized fictional source',repeat('x',1048577),false,clock_timestamp(),clock_timestamp() FROM candidate_profiles WHERE singleton_key='primary'").bind(Uuid::from_u128(970002)).execute(&mut c).await.unwrap();
    assert!(
        OutreachContext::load(&mut c, outreach_input(Some(job)), &contact_settings())
            .await
            .is_err()
    );
    sqlx::query("DELETE FROM candidate_evidence")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE candidate_profiles SET singleton_key='archived'")
        .execute(&mut c)
        .await
        .unwrap();
    let context = outreach_context(&mut c, Some(job)).await;
    let result = context.preview(outreach_input(Some(job))).unwrap();
    assert_eq!(result["status"], "needs_input");
    assert!(
        result["missing_information"]
            .as_array()
            .unwrap()
            .contains(&json!("candidate_profile_required"))
    );
    assert!(result["body"].is_null());
}
