//! Background questionnaire inference shares the existing transient slot with HTTP/document IO.
use super::*;
/// No extra persistent connection, owner/control mutex or browser process during inference.
pub async fn serve(api: Arc<Api>, shutdown: tokio_util::sync::CancellationToken) -> Result<()> {
    let mut backoff = Backoff::default();
    loop {
        tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(Duration::from_secs(5).max(backoff.remaining()))=>{}}
        let Ok(permit) = api.long_request.try_acquire() else {
            continue;
        };
        let pending = {
            let Ok(mut state) = api.connection.try_lock() else {
                continue;
            };
            if state.value.is_none() {
                if !state.backoff.remaining().is_zero() {
                    continue;
                }
                match api.config.connect(false).await {
                    Ok(mut c) => {
                        if readiness(&mut c, &api.config).await.is_ok() {
                            state.value = Some(c);
                            state.backoff.reset();
                        } else {
                            recovery::close(c).await;
                            state.backoff.failed();
                            continue;
                        }
                    }
                    Err(_) => {
                        state.backoff.failed();
                        continue;
                    }
                }
            }
            let c = state
                .value
                .as_mut()
                .ok_or(Failure("agent_database_unavailable"))?;
            match sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM owner_preferences w WHERE starts_with(w.key,'apply_work:') AND w.value->>'platform'='naukri' AND w.value->>'operation'='prepare_questionnaire' AND w.value->>'status'='queued') AND EXISTS(SELECT 1 FROM owner_preferences p WHERE p.key='application_queue_policy' AND p.value->>'state'='RUNNING' AND p.value#>>'{policy,platforms,naukri,enabled}'='true')").fetch_one(c).await{
                Ok(pending)=>pending,
                Err(_)=>{if let Some(c)=state.value.take(){recovery::close(c).await;}state.backoff.failed();backoff.failed();false}
            }
        };
        if !pending {
            continue;
        }
        let mut connection = match api.config.connect(false).await {
            Ok(c) => c,
            Err(_) => {
                backoff.failed();
                continue;
            }
        };
        let result = tokio::select! {
            biased;
            _=shutdown.cancelled()=>Err(Failure("generation_outcome_unknown")),
            result=tokio::time::timeout(Duration::from_secs(40),async{
                readiness(&mut connection,&api.config).await?;
                crate::execution::questionnaire_preparation::prepare_one(&mut connection,crate::execution::questionnaire_preparation::Services{packets:&api.config.packets,answers:&api.config.answers,narratives:api.config.questionnaire_answers.as_ref(),resumes:&api.config.resumes}).await
            })=>result.unwrap_or(Err(Failure("generation_outcome_unknown")))
        };
        if !shutdown.is_cancelled() {
            let status = match result {
                Ok(changed) => {
                    backoff.reset();
                    let status = crate::execution::schedule::record(
                        &mut connection,
                        "apply_generation:naukri",
                        None,
                        Some(json!({"changed":changed,"application_dispatch":false})),
                    )
                    .await;
                    if changed {
                        api.wake.work_available();
                    }
                    status
                }
                Err(error) => {
                    backoff.failed();
                    if !recovery::database_failure(error) && connection.ping().await.is_ok() {
                        crate::execution::schedule::record(
                            &mut connection,
                            "apply_generation:naukri",
                            Some(error),
                            None,
                        )
                        .await
                    } else {
                        Ok(())
                    }
                }
            };
            if let Err(error) = status {
                backoff.failed();
                eprintln!("{}", error.0);
            }
        }
        recovery::close(connection).await;
        drop(permit);
        if shutdown.is_cancelled() {
            return Ok(());
        }
    }
}
