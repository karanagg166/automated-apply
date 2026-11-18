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
use serde_json::Value;
use sqlx::PgConnection;
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
        if result.is_err()
            && !run.terminal()
            && let Ok(target) = session.plan().abort(&run)
        {
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
        let mut selection = super::dataset::Selection::default();
        for offset in (0..limit).step_by(50) {
            let target = session.plan().dataset(run, &build, offset)?;
            let page_limit = 50.min(limit - offset);
            let page = session
                .exchange(
                    c,
                    self.client,
                    self.settings,
                    "dataset",
                    target,
                    |plan, body| {
                        let page = super::dataset::page(plan, run.id(), body, offset, observed)?;
                        Ok((page.clone(), page))
                    },
                )
                .await?;
            selection.push(&page)?;
            if page["returned"]
                .as_u64()
                .ok_or(Failure("apify_dataset_schema_invalid"))?
                < page_limit
            {
                break;
            }
        }
        let finding = selection.finding(session.plan().portal(), Utc::now());
        session.finish_finding(c, finding).await
    }
}
