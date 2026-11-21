//! One coherent saved catalog; filter/rank the complete bounded candidate set before paging.
use super::{
    contract::{self, Kind},
    detail, rules,
};
use crate::{Failure, Result};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::BTreeMap;
use uuid::Uuid;
#[derive(Clone, Copy)]
pub enum Route {
    Search,
    Shortlist,
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/startups/search" => Some(Route::Search),
        "/api/v1/startups/shortlist" => Some(Route::Shortlist),
        _ => None,
    }
}
fn invalid() -> Failure {
    Failure("invalid_startup_catalog_record")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_catalog_database_error")
}
fn strings(v: &Value) -> Result<Vec<String>> {
    v.as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|s| s.as_str().map(String::from).ok_or_else(invalid))
        .collect()
}
fn timestamp(v: &Value) -> Result<DateTime<Utc>> {
    let stamp = crate::packet_record::timestamp(v, true).map_err(|_| invalid())?;
    DateTime::parse_from_rfc3339(stamp.as_str().ok_or_else(invalid)?)
        .map(|t| t.to_utc())
        .map_err(|_| invalid())
}
pub fn matches_status(job: &Value, packets: &[Value], status: &str) -> bool {
    let submitted = job["status"] == "applied"
        || packets.iter().any(|p| {
            matches!(
                p["lifecycle_state"].as_str(),
                Some("user_reported_submitted" | "provider_confirmed_submitted")
            )
        });
    match status {
        "not_applied" => !submitted,
        "applied" => submitted,
        "packet_prepared" => !packets.is_empty() && !submitted,
        "shortlisted" => job["status"] == "shortlisted",
        "interview" => packets
            .iter()
            .any(|p| p["tracking_state"] == "interview_scheduled"),
        "rejected" => {
            job["status"] == "rejected"
                || packets
                    .iter()
                    .any(|p| p["tracking_state"] == "application_rejected")
        }
        _ => true,
    }
}
fn country(s: &str) -> String {
    let value = folded(s.trim_matches(crate::context_contract::python_space));
    match value.as_str() {
        "in" | "ind" => "india".into(),
        _ => value,
    }
}
pub fn allowed(
    item: &Value,
    jobs: &[Value],
    packets: &BTreeMap<String, Vec<Value>>,
    filters: &Value,
) -> Result<bool> {
    if let Some(query) = filters["query"].as_str().filter(|s| !s.is_empty()) {
        let text = format!(
            "{} {}",
            item["company_name"].as_str().ok_or_else(invalid)?,
            item["company_domain"].as_str().unwrap_or("")
        );
        if !folded(&text).contains(&folded(query)) {
            return Ok(false);
        }
    }
    let status = filters["application_status"].as_str().ok_or_else(invalid)?;
    if status != "all"
        && !(status == "not_applied" && jobs.is_empty()
            || status == "shortlisted" && item["shortlisted"] == true)
        && !jobs.iter().any(|j| {
            matches_status(
                j,
                packets
                    .get(j["id"].as_str().unwrap_or(""))
                    .map(Vec::as_slice)
                    .unwrap_or(&[]),
                status,
            )
        })
    {
        return Ok(false);
    }
    if !rules::size_allowed(item, filters)?
        || !item["exclusion_reasons"]
            .as_array()
            .ok_or_else(invalid)?
            .is_empty()
        || item["startup_match_score"].as_f64().ok_or_else(invalid)?
            < filters["minimum_score"].as_f64().ok_or_else(invalid)?
    {
        return Ok(false);
    }
    let attrs = &item["attributes"];
    if filters["country"].as_str().is_some_and(|s| {
        !s.is_empty() && country(s) != country(attrs["country"].as_str().unwrap_or(""))
    }) {
        return Ok(false);
    }
    if !rules::industry_allowed(
        attrs["industry"].as_str(),
        &strings(&filters["industries"])?,
    ) {
        return Ok(false);
    }
    for (flag, count) in [
        ("has_technical_staff", "technical_staff_count"),
        ("has_leader_evidence", "leader_evidence_count"),
        ("has_business_email", "qualified_business_mailbox_count"),
    ] {
        if filters[flag] == true && item[count].as_u64().ok_or_else(invalid)? == 0 {
            return Ok(false);
        }
    }
    if filters["verified_yc"] == true && attrs["yc_batch"].as_str().is_none_or(str::is_empty) {
        return Ok(false);
    }
    if filters["early_stage"] == true
        && !matches!(
            folded(attrs["stage"].as_str().unwrap_or("")).as_str(),
            "pre-seed" | "seed" | "early" | "early-stage" | "series a"
        )
    {
        return Ok(false);
    }
    if !filters["observed_after"].is_null() {
        let after = timestamp(&filters["observed_after"])?;
        if !jobs.iter().any(|j| {
            !j["last_observed_at"].is_null()
                && timestamp(&j["last_observed_at"]).is_ok_and(|at| at > after)
        }) {
            return Ok(false);
        }
    }
    let stages = strings(&filters["stages"])?;
    if !stages.is_empty()
        && !attrs["stage"]
            .as_str()
            .is_some_and(|stage| stages.iter().any(|s| s == stage))
    {
        return Ok(false);
    }
    for key in ["yc_batch", "hiring_status"] {
        if !filters[key].is_null()
            && filters[key]
                != if key == "yc_batch" {
                    attrs[key].clone()
                } else {
                    item[key].clone()
                }
        {
            return Ok(false);
        }
    }
    let evidence = item["hiring_evidence"].as_array().ok_or_else(invalid)?;
    let fresh = evidence
        .iter()
        .filter(|e| e["fresh"] == true)
        .collect::<Vec<_>>();
    let roles = strings(&filters["roles"])?;
    if !roles.is_empty()
        && item["matching_roles"].as_u64().ok_or_else(invalid)? == 0
        && !fresh.iter().any(|e| {
            e["title"]
                .as_str()
                .is_some_and(|title| rules::role_allowed(title, &roles))
        })
    {
        return Ok(false);
    }
    let skills = strings(&filters["skills"])?;
    if !skills.is_empty() {
        let attrs_skills = if attrs["technology_stack"].is_null() {
            vec![]
        } else {
            strings(&attrs["technology_stack"])?
        };
        let matched = skills
            .iter()
            .any(|skill| attrs_skills.iter().any(|s| folded(skill) == folded(s)))
            || jobs.iter().any(|j| {
                j["skills_required"].as_array().is_some_and(|a| {
                    a.iter().any(|v| {
                        v.as_str()
                            .is_some_and(|s| skills.iter().any(|skill| folded(skill) == folded(s)))
                    })
                })
            });
        if !matched {
            return Ok(false);
        }
    }
    let mut locations = vec![attrs["location"].as_str().unwrap_or("").to_owned()];
    let mut remotes = vec![attrs["remote_policy"].as_str().unwrap_or("").to_owned()];
    for e in fresh {
        locations.push(e["location"].as_str().unwrap_or("").to_owned());
        remotes.push(e["remote_policy"].as_str().unwrap_or("").to_owned());
    }
    rules::location_allowed(&locations, &remotes, filters)
}
pub(crate) async fn search_in(
    tx: &mut Transaction<'_, Postgres>,
    filters: &Value,
    shortlisted: bool,
    settings: &crate::contacts::Settings,
    now: DateTime<Utc>,
    scope: Option<&[Uuid]>,
) -> Result<Value> {
    let ids:Vec<Uuid>=sqlx::query_scalar("SELECT c.id FROM companies c WHERE ($3::uuid[] IS NULL OR c.id=ANY($3)) AND (NOT $1 OR EXISTS(SELECT 1 FROM startup_shortlist_entries s WHERE s.company_id=c.id)) AND ($2::text IS NULL OR EXISTS(SELECT 1 FROM company_source_observations o WHERE o.company_id=c.id AND o.source=$2) OR EXISTS(SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.source_platform=$2)) ORDER BY c.id LIMIT 5001").bind(shortlisted).bind(filters["source"].as_str()).bind(scope.map(|ids|ids.to_vec())).fetch_all(&mut **tx).await.map_err(db)?;
    if ids.len() > 5000 {
        return Err(Failure("startup_catalog_company_limit"));
    }
    let packet_rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('job_id',p.job_id,'lifecycle_state',p.lifecycle_state,'tracking_state',p.tracking_state) FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE j.company_id=ANY($1) ORDER BY p.job_id,p.id LIMIT 10001").bind(&ids).fetch_all(&mut **tx).await.map_err(db)?;
    if packet_rows.len() > 10000 {
        return Err(Failure("startup_catalog_packet_limit"));
    }
    let mut packets = BTreeMap::<String, Vec<Value>>::new();
    for row in packet_rows {
        let id = row["job_id"].as_str().ok_or_else(invalid)?.to_owned();
        packets.entry(id).or_default().push(row);
    }
    let profile = detail::profile_in(tx, filters["use_profile"] == true).await?;
    let mut items = Vec::new();
    let (mut bytes, mut jobs_count) = (0_usize, 0_usize);
    for batch in ids.chunks(100) {
        for snapshot in
            detail::snapshots_in(tx, batch, filters, profile.as_ref(), settings, now).await?
        {
            jobs_count += snapshot.jobs.len();
            if jobs_count > 10000 {
                return Err(Failure("startup_catalog_job_limit"));
            }
            let mut item = snapshot.public;
            if allowed(&item, &snapshot.jobs, &packets, filters)? {
                item["application_history"]=json!(snapshot.jobs.iter().map(|j|{let p=packets.get(j["id"].as_str().unwrap_or(""));json!({"job_id":j["id"],"title":j["title"],"status":j["status"],"lifecycle_state":p.and_then(|rows|rows.first()).map(|v|v["lifecycle_state"].clone()),"packet_states":p.map(|rows|rows.iter().map(|v|json!({"lifecycle_state":v["lifecycle_state"],"tracking_state":v["tracking_state"]})).collect::<Vec<_>>()).unwrap_or_default()})}).collect::<Vec<_>>());
                bytes += item.to_string().len();
                if bytes > 16 * 1024 * 1024 {
                    return Err(Failure("startup_catalog_projection_limit"));
                }
                items.push(item);
            }
        }
    }
    items.sort_by(|a, b| {
        b["startup_match_score"]
            .as_f64()
            .unwrap_or(0.0)
            .total_cmp(&a["startup_match_score"].as_f64().unwrap_or(0.0))
            .then_with(|| {
                folded(a["company_name"].as_str().unwrap_or(""))
                    .cmp(&folded(b["company_name"].as_str().unwrap_or("")))
            })
            .then_with(|| a["company_id"].as_str().cmp(&b["company_id"].as_str()))
    });
    let total = items.len();
    let page = filters["page"].as_u64().ok_or_else(invalid)?;
    let limit = filters["limit"].as_u64().ok_or_else(invalid)?;
    let selected = items
        .into_iter()
        .skip(((page - 1) * limit) as usize)
        .take(limit as usize)
        .collect::<Vec<_>>();
    Ok(
        json!({"total":total,"page":page,"limit":limit,"startups":selected,"evidence_basis":"saved_local_records","live_verified":false}),
    )
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    let filters = match method {
        "GET" => {
            if !body.is_empty() {
                return Err(Failure("invalid_startup_query"));
            }
            contract::query(query)?
        }
        "POST" if matches!(route, Route::Search) => {
            if query.is_some() {
                return Err(Failure("invalid_startup_query"));
            }
            contract::normalize(
                Kind::Filters,
                serde_json::from_slice(body).map_err(|_| Failure("invalid_startup_contract"))?,
            )?
        }
        _ => return Err(Failure("startup_catalog_method_not_allowed")),
    };
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = timestamp(&now)?;
    let result = search_in(
        &mut tx,
        &filters,
        matches!(route, Route::Shortlist),
        settings,
        now,
        None,
    )
    .await?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_catalog_read_commit_failed"))?;
    Ok(result)
}
