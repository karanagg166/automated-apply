//! Questionnaire inference and approved mailbox alerts share the existing transient IO slot.
use super::*;
#[derive(Clone, Copy)]
enum Work {
    Questionnaire,
    Alert(crate::mailboxes::Slot),
}
/// No extra persistent connection, owner/control mutex or browser process during inference.
pub async fn serve(api: Arc<Api>, shutdown: tokio_util::sync::CancellationToken) -> Result<()> {
    let mut backoff = Backoff::default();
    let mut prefer_alert = false;
    loop {
        tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(Duration::from_secs(5).max(backoff.remaining()))=>{}}
        let Ok(permit) = api.long_request.try_acquire() else {
            continue;
        };
        let (pending, alert) = {
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
            let hint=async{
                let pending=sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM owner_preferences w WHERE starts_with(w.key,'apply_work:') AND w.value->>'platform'='naukri' AND w.value->>'operation'='prepare_questionnaire' AND w.value->>'status'='queued') AND EXISTS(SELECT 1 FROM owner_preferences p WHERE p.key='application_queue_policy' AND p.value->>'state'='RUNNING' AND p.value#>>'{policy,platforms,naukri,enabled}'='true')").fetch_one(&mut *c).await.map_err(|_|Failure("execution_database_error"))?;
                let alert=crate::mailboxes::alerts::due(c,&api.config.mailboxes).await?;
                Ok::<_,Failure>((pending,alert))
            }.await;
            match hint {
                Ok(hint) => hint,
                Err(_) => {
                    if let Some(c) = state.value.take() {
                        recovery::close(c).await;
                    }
                    state.backoff.failed();
                    backoff.failed();
                    (false, None)
                }
            }
        };
        let work = match (pending, alert) {
            (true, Some(slot)) => {
                let work = if prefer_alert {
                    Work::Alert(slot)
                } else {
                    Work::Questionnaire
                };
                prefer_alert = !prefer_alert;
                work
            }
            (true, None) => Work::Questionnaire,
            (false, Some(slot)) => Work::Alert(slot),
            (false, None) => continue,
        };
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
            result=tokio::time::timeout(Duration::from_secs(if matches!(work,Work::Alert(_)){105}else{40}),async{
                readiness(&mut connection,&api.config).await?;
                match work {
                    Work::Questionnaire=>crate::execution::questionnaire_preparation::prepare_one(&mut connection,crate::execution::questionnaire_preparation::Services{packets:&api.config.packets,answers:&api.config.answers,narratives:api.config.questionnaire_answers.as_ref(),resumes:&api.config.resumes}).await,
                    Work::Alert(slot)=>{
                        let service=crate::mailboxes::Service{settings:&api.config.mailboxes,provider:&api.config.mailboxes};
                        service.poll_alerts(&mut connection,slot,false,api.config.telegram.as_ref()).await.map(|value|value["status"]=="observed")
                    }
                }
            })=>result.unwrap_or(Err(Failure("generation_outcome_unknown")))
        };
        if !shutdown.is_cancelled() {
            let status = match result {
                Ok(changed) => {
                    backoff.reset();
                    let status = if matches!(work, Work::Questionnaire) {
                        crate::execution::schedule::record(
                            &mut connection,
                            "apply_generation:naukri",
                            None,
                            Some(json!({"changed":changed,"application_dispatch":false})),
                        )
                        .await
                    } else {
                        Ok(())
                    };
                    if changed {
                        api.wake.work_available();
                    }
                    status
                }
                Err(error) => {
                    backoff.failed();
                    if matches!(work, Work::Questionnaire)
                        && !recovery::database_failure(error)
                        && connection.ping().await.is_ok()
                    {
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
