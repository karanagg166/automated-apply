//! Typed private-owner Naukri commands use the dashboard's durable controls, never direct Apply.
use super::{
    legacy_policy, owner_routes, owner_status, queue, queue_control, queue_page::Page,
    queue_status, storage::*,
};
use crate::{Failure, Result, configuration::Configuration};
use chrono::{DateTime, Utc};
use serde_json::json;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    Status,
    Queue(Option<String>),
    Add(String),
    Automation(String),
    Find,
    Apply(Vec<Uuid>),
    Control { action: String, id: Uuid },
    Help,
}
impl Command {
    pub fn mutates(&self) -> bool {
        matches!(
            self,
            Self::Queue(Some(_))
                | Self::Add(_)
                | Self::Automation(_)
                | Self::Apply(_)
                | Self::Control { .. }
        )
    }
}
pub fn parse(text: &str, bot: &str) -> Option<Command> {
    let words = text
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();
    let first = *words.first()?;
    let (name, mention) = first
        .split_once('@')
        .map(|(a, b)| (a, Some(b)))
        .unwrap_or((first, None));
    if name != "/naukri" {
        return None;
    }
    if text.chars().count() > 2048 || mention.is_some_and(|s| !s.eq_ignore_ascii_case(bot)) {
        return Some(Command::Help);
    }
    let command = match &words[1..] {
        [] | ["status"] => Command::Status,
        ["queue"] => Command::Queue(None),
        ["queue", action] if matches!(*action, "start" | "pause" | "resume" | "stop") => {
            Command::Queue(Some(
                if *action == "resume" { "start" } else { action }.to_string(),
            ))
        }
        ["add", url] => Command::Add((*url).into()),
        ["automation", action] if matches!(*action, "start" | "pause" | "stop") => {
            Command::Automation((*action).into())
        }
        ["find"] => Command::Find,
        ["apply", ids @ ..] if (1..=25).contains(&ids.len()) => match ids
            .iter()
            .map(|s| s.parse::<Uuid>())
            .collect::<std::result::Result<Vec<_>, _>>()
        {
            Ok(ids) => Command::Apply(ids),
            Err(_) => Command::Help,
        },
        [action, id] if matches!(*action, "pause" | "resume" | "cancel") => match id.parse() {
            Ok(id) => Command::Control {
                action: (*action).into(),
                id,
            },
            Err(_) => Command::Help,
        },
        _ => Command::Help,
    };
    Some(command)
}
pub(crate) async fn execute_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<String> {
    let output=match command{
  Command::Help=>"/naukri add <job URL> | queue [start|pause|resume|stop] | automation start|pause|stop | find | apply <saved job UUID...> | pause|resume|cancel <execution UUID> | status. Preparation and queue controls retain current limits; this command never dispatches Apply.".into(),
  Command::Add(url)=>{let work=queue::enqueue_in(tx,url,"saved_verified_job",None,now).await?;format!("Naukri queue {}: {}. No application sent by this command.",work["id"].as_str().ok_or_else(invalid)?,work["stage"].as_str().ok_or_else(invalid)?)},
  Command::Queue(Some(action))=>{let current=queue_control::configuration(tx).await?;let value=queue_control::control(tx,json!({"action":action,"expected_revision":current["revision"]}),now).await?;format!("Naukri queue: {}; saved policy, first-receipt prerequisite and submission limits remain enforced. Live acceptance remains pending.",value["state"].as_str().ok_or_else(invalid)?)},
  Command::Queue(None)=>{let value=queue_status::listing(tx,Page{platform:Some("naukri".into()),limit:5,..Page::default()}).await?;format!("Naukri queue: {}; {}. Status is retained evidence, not a new application receipt.",value["configuration"]["state"].as_str().ok_or_else(invalid)?,value["counts"])},
  Command::Automation(action)=>{let current=legacy_policy::record(tx).await?;let value=legacy_policy::control_in(tx,json!({"action":action,"expected_revision":current["revision"]}),now).await?;format!("Naukri automation: {}; preparation only; no browser submission dispatched by this command.",value["state"].as_str().ok_or_else(invalid)?)},
  Command::Apply(ids)=>{let result=owner_routes::start_in(tx,json!({"job_ids":ids}),now).await?;result.as_array().ok_or_else(invalid)?.iter().map(|e|Ok(format!("{}: {}; preparation only, no submission.",e["id"].as_str().ok_or_else(invalid)?,e["state"].as_str().ok_or_else(invalid)?))).collect::<Result<Vec<_>>>()?.join("\n")},
  Command::Control{action,id}=>{let current=get(tx,&format!("exec:{id}")).await?.ok_or(Failure("execution_not_found"))?;let value=owner_routes::intent_control_in(tx,*id,&json!({"action":action,"expected_revision":current["revision"]}),now).await?;format!("Legacy preparation {id}: {}. Application queue controls are separate: /naukri queue pause. Check saved history before manual submission.",value["state"].as_str().ok_or_else(invalid)?)},
  Command::Find=>{let rows:Vec<(Uuid,String)>=sqlx::query_as("SELECT id,title FROM jobs WHERE source_platform='naukri' ORDER BY created_at DESC,id LIMIT 20").fetch_all(&mut **tx).await.map_err(db)?;let lines=rows.into_iter().map(|(id,title)|format!("{id} — {}",title.chars().take(40).collect::<String>())).collect::<Vec<_>>();format!("Saved owner-imported Naukri jobs; no portal search executed:\n{}",if lines.is_empty(){"None. Import exact job facts in the dashboard.".into()}else{lines.join("\n")})},
  Command::Status=>{let status=owner_status::status_in(tx,Some(config),now).await?;let queue=queue_status::listing(tx,Page{platform:Some("naukri".into()),limit:5,..Page::default()}).await?;let automation=&status["automation"];format!("Naukri queue: {}; {}. Live installed acceptance pending.\nLegacy preparation: {}; worker {}; source {}.\nCounts: {}. Blockers: {}.",queue["configuration"]["state"].as_str().ok_or_else(invalid)?,queue["counts"],automation["state"].as_str().ok_or_else(invalid)?,if automation["worker_online"]==true{"online"}else{"offline"},automation["source"].as_str().ok_or_else(invalid)?,automation["counts"],automation["blockers"])},
 };
    // Do not echo raw URLs, query tokens, resumes, answers or compensation in command replies.
    let mut used = 0;
    Ok(output
        .chars()
        .take_while(|c| {
            used += c.len_utf16();
            used <= 3400
        })
        .collect())
}
pub(crate) async fn dispatch_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<String> {
    let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    match execute_in(&mut savepoint, command, config, now).await {
        Ok(reply) => {
            savepoint.commit().await.map_err(db)?;
            Ok(reply)
        }
        Err(error) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            if super::denial(error)
                || matches!(
                    error.0,
                    "execution_mode_off"
                        | "naukri_automation_paused"
                        | "naukri_automation_stopped"
                        | "queue_source_disabled"
                        | "queue_backpressure"
                        | "prior_receipt_requires_reconciliation_no_replay"
                        | "prior_application_or_unknown_submission_no_replay"
                        | "naukri_job_url_required"
                        | "naukri_posting_path_required"
                        | "public_https_job_url_required"
                        | "invalid_job_url"
                )
            {
                Ok(format!(
                    "Naukri command rejected: {}. Review the exact saved reference and current policy in the dashboard.",
                    error.0
                ))
            } else {
                Err(error)
            }
        }
    }
}
