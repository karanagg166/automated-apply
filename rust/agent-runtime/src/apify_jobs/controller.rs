//! Original paid run lifecycle. Replays return saved state and cannot restart provider acquisition.
use super::{
    admission::{self, Admission},
    evidence::{ActorIdentity, Run, VerifiedBuild},
    session::Session,
    settings::Settings,
    transport::Client,
};
use crate::{Failure, Result};
use chrono::Utc;
use serde_json::{Value, json};
use sqlx::PgConnection;
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
}
impl Service<'_> {
    pub async fn acquire(&self, c: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
        let claim = match admission::admit(c, self.settings, input, id).await? {
            Admission::Retained(value) => return Ok(value),
            Admission::Original(claim) => claim,
        };
        self.acquire_original(c, *claim).await
    }
    pub(super) async fn acquire_original(
        &self,
        c: &mut PgConnection,
        claim: admission::Claim,
    ) -> Result<Value> {
        let id = claim.request_id();
        let mut session = Session::original(claim)?;
        let target = session.plan().actor_metadata()?;
        let actor = session
            .exchange(
                c,
                self.client,
                self.settings,
                "actor",
                target,
                |plan, body| {
                    let identity = ActorIdentity::parse(plan, body)?;
                    let selected = identity.selected();
                    Ok((identity, selected))
                },
            )
            .await?;
        let target = session.plan().reviewed_build(&actor)?;
        let build = session
            .exchange(
                c,
                self.client,
                self.settings,
                "reviewed_build",
                target,
                |plan, body| {
                    let build = VerifiedBuild::review(plan, &actor, body)?;
                    let selected = build.selected();
                    Ok((build, selected))
                },
            )
            .await?;
        let target = session.plan().start(&actor, &build)?;
        let admitted = session.started()?;
        let mut run = session
            .exchange(
                c,
                self.client,
                self.settings,
                "start",
                target,
                |plan, body| {
                    let run = Run::parse(plan, &actor, body, None, admitted, Utc::now())?;
                    let selected = run.selected();
                    Ok((run, selected))
                },
            )
            .await?;
        let result = self.collect(c, &mut session, &actor, &mut run).await;
        if let Err(error) = result {
            let _ = session.note_failure(c, error).await;
        }
        if result.is_err() && !run.terminal() {
            if let Ok(target) = session.plan().abort(&run) {
                // A single admitted abort is best effort; original deadline/cap remain the fallback.
                let _ = session
                    .exchange(
                        c,
                        self.client,
                        self.settings,
                        "abort",
                        target,
                        |plan, body| {
                            let observed =
                                Run::parse(plan, &actor, body, Some(&run), admitted, Utc::now())?;
                            let selected = observed.selected();
                            Ok((observed, selected))
                        },
                    )
                    .await;
            }
        }
        result?;
        admission::read(c, id).await
    }
    async fn collect(
        &self,
        c: &mut PgConnection,
        session: &mut Session,
        actor: &ActorIdentity,
        run: &mut Run,
    ) -> Result<()> {
        let admitted = session.started()?;
        for _ in 0..3 {
            if run.terminal() {
                break;
            }
            let target = session.plan().status(run)?;
            let next = session
                .exchange(
                    c,
                    self.client,
                    self.settings,
                    "status",
                    target,
                    |plan, body| {
                        let next = Run::parse(plan, actor, body, Some(run), admitted, Utc::now())?;
                        let selected = next.selected();
                        Ok((next, selected))
                    },
                )
                .await?;
            *run = next;
        }
        if !run.succeeded() {
            return Err(Failure("apify_original_run_not_succeeded"));
        }
        let target = session.plan().build_metadata(run)?;
        let build = session
            .exchange(
                c,
                self.client,
                self.settings,
                "run_build",
                target,
                |plan, body| {
                    let build = VerifiedBuild::parse(plan, run, body)?;
                    let selected = build.selected();
                    Ok((build, selected))
                },
            )
            .await?;
        let limit = session.plan().query["limit"]
            .as_u64()
            .ok_or(Failure("invalid_apify_original_intent"))?;
        let observed = Utc::now();
        let mut jobs = BTreeMap::<String, Value>::new();
        let mut conflicts = BTreeSet::<String>::new();
        let mut rejected = 0_u64;
        let mut duplicate = 0_u64;
        for offset in (0..limit).step_by(50) {
            let target = session.plan().dataset(run, &build, offset)?;
            let page_limit = 50.min(limit - offset);
            let page=session.exchange(c,self.client,self.settings,"dataset",target,|plan,body|{
                let rows=body.as_array().filter(|a|a.len() as u64<=page_limit).ok_or(Failure("apify_dataset_schema_invalid"))?;
                let mut selected=Vec::new();let mut invalid=0;
                for row in rows {
                    match super::record::normalize(plan.portal(),plan.actor["actor_id"].as_str().ok_or(Failure("apify_actor_id_invalid"))?,row,observed){Ok(mut job)=>{
                        job["data_provenance"]["provider_run_id"]=json!(run.id());job["data_provenance"]["actor_build"]=plan.actor["build"].clone();selected.push(job);
                    },Err(_)=>invalid+=1}
                }
                let page=json!({"offset":offset,"limit":page_limit,"returned":rows.len(),"rejected":invalid,"jobs":selected});Ok((page.clone(),page))
            }).await?;
            rejected += page["rejected"]
                .as_u64()
                .ok_or(Failure("apify_dataset_schema_invalid"))?;
            for job in page["jobs"]
                .as_array()
                .ok_or(Failure("apify_dataset_schema_invalid"))?
            {
                let identity = crate::job_sources::identity::observation_key(job)?;
                if conflicts.contains(&identity) {
                    rejected += 1;
                    continue;
                }
                if let Some(previous) = jobs.get(&identity) {
                    if previous == job {
                        duplicate += 1
                    } else {
                        jobs.remove(&identity);
                        conflicts.insert(identity);
                        rejected += 2
                    }
                } else {
                    jobs.insert(identity, job.clone());
                }
            }
            if page["returned"]
                .as_u64()
                .ok_or(Failure("apify_dataset_schema_invalid"))?
                < page_limit
            {
                break;
            }
        }
        let rows = jobs.into_values().collect::<Vec<_>>();
        let at = Utc::now();
        let finding = json!({"source":session.plan().portal(),"status":if rejected>0{"partial"}else if rows.is_empty(){"no_results"}else{"success"},"jobs":rows,"rejected_count":rejected,"duplicate_count":duplicate,"observed_at":at.to_rfc3339(),"application_dispatch":false,"live_verified":false,"billing_final":false});
        session.finish_finding(c, finding).await
    }
}
