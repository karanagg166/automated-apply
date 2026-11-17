//! Deferred existing owner-preference memory with disposable records only.
use automated_apply_agents::conversation::{intent as conversation_intent,memory as conversation_memory};
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn conversation_memory_uses_original_owner_key_and_retains_eight_categories_without_raw_input() {
    let mut c=knowledge_fixture().await;let mut tx=c.begin().await.unwrap();
    let mut loaded=conversation_memory::load_in(&mut tx,111).await.unwrap();let id=loaded.conversation_id().unwrap();let intent=conversation_intent::deterministic("find Rust jobs");
    for _ in 0..10{conversation_memory::record_in(&mut tx,&mut loaded,&intent).await.unwrap();}
    assert_eq!(loaded.value()["history"].as_array().unwrap().len(),8);assert!(!loaded.value().to_string().contains("find Rust jobs"));assert_eq!(loaded.conversation_id().unwrap(),id);
    let other=conversation_memory::load_in(&mut tx,222).await.unwrap();assert_ne!(other.conversation_id().unwrap(),id);tx.commit().await.unwrap();
    let saved:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(automated_apply_agents::telegram_local::context_key(111)).fetch_one(&mut c).await.unwrap();assert_eq!(saved["conversation_id"],json!(id));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn expired_selection_gets_fresh_proposal_without_rewriting_saved_history_on_load() {
    let mut c=knowledge_fixture().await;let key=automated_apply_agents::telegram_local::context_key(111);let old=Uuid::new_v4();
    let saved=json!({"conversation_id":old,"history":[],"job_ids":[],"selected_job_id":null,"project_id":null,"clarification":null,"expires_at":(chrono::Utc::now()-chrono::Duration::minutes(1)).to_rfc3339()});
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)").bind(&key).bind(&saved).execute(&mut c).await.unwrap();
    let mut tx=c.begin().await.unwrap();let loaded=conversation_memory::load_in(&mut tx,111).await.unwrap();assert_ne!(loaded.conversation_id().unwrap(),old);tx.commit().await.unwrap();
    let retained:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(&key).fetch_one(&mut c).await.unwrap();assert_eq!(retained,saved);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn malformed_unknown_or_oversized_memory_is_preserved_and_never_silently_replaced() {
    let mut c=knowledge_fixture().await;let key=automated_apply_agents::telegram_local::context_key(111);
    for value in [json!({"conversation_id":"broken","history":[],"job_ids":[]}),json!({"raw_message":"private"}),json!({"oversized":"x".repeat(32769)})] {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value").bind(&key).bind(&value).execute(&mut c).await.unwrap();
        let mut tx=c.begin().await.unwrap();assert!(conversation_memory::load_in(&mut tx,111).await.is_err());tx.rollback().await.unwrap();
        assert_eq!(sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key=$1").bind(&key).fetch_one(&mut c).await.unwrap(),value);
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn conversation_identity_changes_require_explicit_reset_and_stale_snapshot_cannot_overwrite() {
    let mut c=knowledge_fixture().await;let mut tx=c.begin().await.unwrap();let mut loaded=conversation_memory::load_in(&mut tx,111).await.unwrap();
    let old=loaded.conversation_id().unwrap();let mut changed=loaded.value().clone();changed["conversation_id"]=json!(Uuid::new_v4());assert_eq!(conversation_memory::save_in(&mut tx,&mut loaded,changed).await.err().unwrap().0,"conversation_identity_changed");
    conversation_memory::reset_in(&mut tx,&mut loaded).await.unwrap();assert_ne!(loaded.conversation_id().unwrap(),old);assert_eq!(loaded.value()["job_ids"],json!([]));
    let key=automated_apply_agents::telegram_local::context_key(111);sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{clarification}','\"choose_one_request\"') WHERE key=$1").bind(&key).execute(&mut *tx).await.unwrap();
    let same=loaded.value().clone();assert_eq!(conversation_memory::save_in(&mut tx,&mut loaded,same).await.err().unwrap().0,"conversation_memory_changed");tx.rollback().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn memory_final_ack_detects_after_trigger_mutation_and_whole_turn_rolls_back() {
    let mut c=knowledge_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_mutate_conversation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'telegram_context_') AND NEW.value->>'clarification' IS NULL THEN UPDATE owner_preferences SET value=jsonb_set(NEW.value,'{clarification}','\"choose_one_request\"') WHERE key=NEW.key;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_mutate_conversation AFTER INSERT OR UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_mutate_conversation()").execute(&mut c).await.unwrap();
    let mut tx=c.begin().await.unwrap();let mut loaded=conversation_memory::load_in(&mut tx,111).await.unwrap();let intent=conversation_intent::deterministic("show jobs");assert_eq!(conversation_memory::record_in(&mut tx,&mut loaded,&intent).await.err().unwrap().0,"conversation_memory_write_ack_failed");tx.rollback().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key=$1").bind(automated_apply_agents::telegram_local::context_key(111)).fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER fixture_mutate_conversation ON owner_preferences;DROP FUNCTION fixture_mutate_conversation()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn memory_does_not_accept_an_unbound_or_nonpositive_owner_identity() {
    let mut c=knowledge_fixture().await;let mut tx=c.begin().await.unwrap();
    for owner in [0,-1]{assert_eq!(conversation_memory::load_in(&mut tx,owner).await.err().unwrap().0,"conversation_owner_binding_required");}
    tx.rollback().await.unwrap();
}
