//! Selected public posting fields only; raw provider dictionaries/recruiter identities are excluded.
use super::{contract, rules};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::sync::LazyLock;
fn invalid() -> Failure {
    Failure("public_job_record_invalid")
}
fn begin(item: &Value) -> Result<()> {
    if !item.is_object() || item.to_string().len() > 1048576 {
        return Err(invalid());
    }
    Ok(())
}
fn string<'a>(item: &'a Value, key: &str) -> Result<&'a str> {
    item[key].as_str().ok_or_else(invalid)
}
fn object(value: &Value) -> Result<Value> {
    if value.is_null() {
        Ok(json!({}))
    } else if value.is_object() {
        Ok(value.clone())
    } else {
        Err(invalid())
    }
}
fn identifier(value: &Value) -> Result<String> {
    let id = match value {
        Value::String(s) => s.clone(),
        Value::Number(n) if n.is_i64() || n.is_u64() => n.to_string(),
        _ => return Err(invalid()),
    };
    if id.is_empty() || id.len() > 255 {
        return Err(invalid());
    }
    Ok(id)
}
fn choose(item: &Value, first: &str, second: &str) -> Value {
    if match &item[first] {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    } {
        item[first].clone()
    } else {
        item[second].clone()
    }
}
fn extend(job: &mut Value, fields: Value) {
    job.as_object_mut()
        .expect("record object")
        .extend(fields.as_object().expect("salary fields").clone());
}
fn base(source: &str, item: &Value, title: &str, url: &str, company: Value) -> Value {
    json!({"source_name":source,"title":item[title],"original_url":item[url],"company_name":company,"source_verification_status":"source_reported"})
}
pub fn greenhouse(item: &Value, board: &str, company: &str, now: DateTime<Utc>) -> Result<Value> {
    begin(item)?;
    let location = object(&item["location"])?["name"].clone();
    let mut job = base(
        "greenhouse",
        item,
        "title",
        "absolute_url",
        if item["company_name"].as_str().is_some_and(|s| !s.is_empty()) {
            item["company_name"].clone()
        } else {
            json!(company)
        },
    );
    job["source_job_id"] = json!(identifier(&item["id"])?);
    job["application_url"] = item["absolute_url"].clone();
    job["description"] = item["content"].clone();
    job["location"] = location.clone();
    job["remote_type"] = json!(rules::remote_policy(location.as_str()));
    job["date_posted"] = rules::date(&item["first_published"])?;
    job["is_confirmed_current"] = json!(true);
    job["data_provenance"] = json!({"adapter":"GreenhouseAdapter","board_token":board,"updated_at":item["updated_at"].as_str().filter(|s|s.len()<=100 && DateTime::parse_from_rfc3339(s).is_ok())});
    contract::normalize(job, now)
}
pub fn remotive(item: &Value, now: DateTime<Utc>) -> Result<Value> {
    begin(item)?;
    if !item["salary"].is_null() && !item["salary"].is_string()
        || !item["job_type"].is_null() && !item["job_type"].is_string()
    {
        return Err(invalid());
    }
    let mut job = base(
        "remotive",
        item,
        "title",
        "url",
        item["company_name"].clone(),
    );
    let salary = item["salary"].as_str().filter(|s| !s.is_empty());
    job["source_job_id"] = json!(identifier(&item["id"])?);
    job["description"] = item["description"].clone();
    job["location"] = item["candidate_required_location"].clone();
    job["remote_type"] = json!("remote");
    job["employment_type"] = json!(rules::employment(item["job_type"].as_str()));
    job["salary_raw"] = json!(salary);
    extend(&mut job, rules::salary_fields(salary)?);
    job["skills_required"] = if item["tags"].is_null() {
        json!([])
    } else {
        item["tags"].clone()
    };
    job["date_posted"] = rules::date(&item["publication_date"])?;
    job["data_provenance"] =
        json!({"adapter":"RemotiveAdapter","attribution":"Remotive","feed_delay_hours":24});
    contract::normalize(job, now)
}
pub fn arbeitnow(item: &Value, page: u32, now: DateTime<Utc>) -> Result<Value> {
    begin(item)?;
    if item.get("slug").is_none() {
        return Err(invalid());
    }
    if !(1..=100).contains(&page) {
        return Err(invalid());
    }
    let mut job = base(
        "arbeitnow",
        item,
        "title",
        "url",
        item["company_name"].clone(),
    );
    let types = match item.get("job_types") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(a)) => a
            .iter()
            .map(|v| v.as_str().ok_or_else(invalid))
            .collect::<Result<Vec<_>>>()?,
        _ => return Err(invalid()),
    };
    job["source_job_id"] = item["slug"].clone();
    job["description"] = item["description"].clone();
    job["location"] = item["location"].clone();
    job["remote_type"] = json!(if item["remote"] == true {
        "remote"
    } else {
        "unknown"
    });
    job["employment_type"] = json!(rules::employment(Some(&types.join(" "))));
    job["date_posted"] = rules::date(&item["created_at"])?;
    job["data_provenance"] = json!({"adapter":"ArbeitnowAdapter","page":page,"attribution":"Arbeitnow","attribution_url":"https://www.arbeitnow.com"});
    contract::normalize(job, now)
}
fn application(item: &Value, board: &str, source: &str, region: &str) -> Result<Option<String>> {
    match item.get("applyUrl") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) if s.is_empty() => Ok(None),
        Some(Value::String(s)) => rules::hosted_url(s, board, source, region, true).map(Some),
        _ => Err(invalid()),
    }
}
fn url_path(url: &str) -> Result<String> {
    Ok(reqwest::Url::parse(url)
        .map_err(|_| invalid())?
        .path()
        .trim_end_matches('/')
        .into())
}
pub fn lever(
    item: &Value,
    board: &str,
    company: &str,
    region: &str,
    now: DateTime<Utc>,
) -> Result<Value> {
    begin(item)?;
    if !matches!(region, "global" | "eu") {
        return Err(invalid());
    }
    let id = string(item, "id")?;
    if id.is_empty()
        || id.len() > 100
        || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    {
        return Err(invalid());
    }
    let url = rules::hosted_url(string(item, "hostedUrl")?, board, "lever", region, false)?;
    let path = url_path(&url)?;
    if path.rsplit('/').next() != Some(id) {
        return Err(invalid());
    }
    let application = application(item, board, "lever", region)?;
    if application.as_ref().is_some_and(|s| {
        url_path(s).map_or(true, |p| p.strip_suffix("/apply").unwrap_or(&p) != path)
    }) {
        return Err(invalid());
    }
    let categories = object(&item["categories"])?;
    let salary = object(&item["salaryRange"])?;
    let mut job = json!({"source_name":"lever","source_job_id":id,"original_url":url,"application_url":application,"company_name":company,"title":item["text"],"description":choose(item,"descriptionPlain","description"),"location":categories["location"],"country":item["country"],
        "remote_type":match item["workplaceType"].as_str(){Some("remote")=>"remote",Some("hybrid")=>"hybrid",Some("on-site")=>"onsite",_=>"unknown"},
        "employment_type":match categories["commitment"].as_str(){Some("Full-time")=>Some("full_time"),Some("Part-time")=>Some("part_time"),Some("Contract")=>Some("contract"),Some("Internship")=>Some("internship"),_=>None},
        "salary_raw":item["salaryDescriptionPlain"],"source_verification_status":"source_reported","is_confirmed_current":true,"data_provenance":{"adapter":"LeverAdapter","board_token":format!("{region}:{board}"),"company_name_basis":"operator_configured_board"}});
    extend(
        &mut job,
        rules::structured_salary(
            &salary["min"],
            &salary["max"],
            &salary["currency"],
            &salary["interval"],
            &[
                ("per-year-salary", "year"),
                ("per-month-salary", "month"),
                ("per-week-salary", "week"),
                ("per-day-wage", "day"),
                ("per-hour-wage", "hour"),
            ],
        ),
    );
    contract::normalize(job, now)
}
pub fn ashby(item: &Value, board: &str, company: &str, now: DateTime<Utc>) -> Result<Value> {
    begin(item)?;
    if item["isListed"] != true {
        return Err(invalid());
    }
    let url = rules::hosted_url(string(item, "jobUrl")?, board, "ashby", "global", false)?;
    let path = url_path(&url)?;
    let application = application(item, board, "ashby", "global")?;
    if application.as_ref().is_some_and(|s| {
        url_path(s).map_or(true, |p| {
            p.strip_suffix("/application").unwrap_or(&p) != path
        })
    }) {
        return Err(invalid());
    }
    let remote = match item["workplaceType"].as_str() {
        Some("Remote") => "remote",
        Some("Hybrid") => "hybrid",
        Some("OnSite") => "onsite",
        _ => "unknown",
    };
    if !item["isRemote"].is_null()
        && (!item["isRemote"].is_boolean()
            || remote != "unknown" && item["isRemote"].as_bool() != Some(remote != "onsite"))
    {
        return Err(invalid());
    }
    if !item["publishedAt"].is_null() && !item["publishedAt"].is_string() {
        return Err(invalid());
    }
    let compensation = object(&item["compensation"])?;
    let components = match compensation.get("summaryComponents") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(a)) => a.clone(),
        _ => return Err(invalid()),
    };
    if components.iter().any(|v| !v.is_object()) {
        return Err(invalid());
    }
    let salaries = components
        .iter()
        .filter(|v| v["compensationType"] == "Salary")
        .collect::<Vec<_>>();
    let empty = json!({});
    let salary = if salaries.len() == 1 {
        salaries[0]
    } else {
        &empty
    };
    let mut job = json!({"source_name":"ashby","source_job_id":path.rsplit('/').next(),"original_url":url,"application_url":application,"company_name":company,"title":item["title"],"description":choose(item,"descriptionPlain","descriptionHtml"),"location":item["location"],"remote_type":remote,
        "employment_type":match item["employmentType"].as_str(){Some("FullTime")=>Some("full_time"),Some("PartTime")=>Some("part_time"),Some("Contract")=>Some("contract"),Some("Intern")=>Some("internship"),Some("Temporary")=>Some("temporary"),_=>None},
        "date_posted":rules::date(&item["publishedAt"])? ,"salary_raw":compensation["scrapeableCompensationSalarySummary"],"source_verification_status":"source_reported","is_confirmed_current":true,"data_provenance":{"adapter":"AshbyAdapter","board_token":board,"company_name_basis":"operator_configured_board","publication_basis":"last_published_at"}});
    extend(
        &mut job,
        rules::structured_salary(
            &salary["minValue"],
            &salary["maxValue"],
            &salary["currencyCode"],
            &salary["interval"],
            &[
                ("1 YEAR", "year"),
                ("1 MONTH", "month"),
                ("1 WEEK", "week"),
                ("1 DAY", "day"),
                ("1 HOUR", "hour"),
            ],
        ),
    );
    contract::normalize(job, now)
}
pub fn smartrecruiters(
    item: &Value,
    board: &str,
    company: &str,
    id: &str,
    now: DateTime<Utc>,
) -> Result<Value> {
    begin(item)?;
    if item["id"] != id || item["active"] != true {
        return Err(invalid());
    }
    let employer = string(&item["company"], "identifier")?;
    if automated_apply_domain::text::folded(employer) != automated_apply_domain::text::folded(board)
    {
        return Err(invalid());
    }
    let url = rules::smart_url(string(item, "postingUrl")?, board, id)?;
    let application = match item.get("applyUrl") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) if s.is_empty() => None,
        Some(Value::String(s)) => Some(rules::smart_url(s, board, id)?),
        _ => return Err(invalid()),
    };
    let location = object(&item["location"])?;
    let sections = object(&object(&item["jobAd"])?["sections"])?;
    for key in ["jobDescription", "qualifications", "additionalInformation"] {
        if sections.get(key).is_some_and(|v| !v.is_object()) {
            return Err(invalid());
        }
    }
    let description = ["jobDescription", "qualifications", "additionalInformation"]
        .iter()
        .filter_map(|k| sections[*k]["text"].as_str())
        .collect::<Vec<_>>()
        .join("\n\n");
    let mut locations = Vec::new();
    for key in ["city", "region", "country"] {
        if let Some(value) = location
            .get(key)
            .filter(|v| !v.is_null() && **v != json!("") && **v != false && **v != 0)
        {
            locations.push(match value {
                Value::String(s) => s.clone(),
                Value::Number(n) => n.to_string(),
                _ => return Err(invalid()),
            });
        }
    }
    if !item["releasedDate"].is_null() && !item["releasedDate"].is_string() {
        return Err(invalid());
    }
    contract::normalize(
        json!({"source_name":"smartrecruiters","source_job_id":id,"original_url":url,"application_url":application,"company_name":company,"title":item["name"],"description":if description.is_empty(){None}else{Some(description)},"location":if locations.is_empty(){None}else{Some(locations.join(", "))},"country":location["country"],"region":location["region"],"remote_type":if location["remote"]==true{"remote"}else{"unknown"},"employment_type":rules::employment(object(&item["typeOfEmployment"])?["label"].as_str()),"experience_level":object(&item["experienceLevel"])?["label"],"date_posted":rules::date(&item["releasedDate"])? ,"source_verification_status":"source_reported","is_confirmed_current":true,"data_provenance":{"adapter":"SmartRecruitersAdapter","board_token":board,"company_name_basis":"operator_configured_board","publication_basis":"releasedDate","public_posting_id":id}}),
        now,
    )
}
pub fn hacker_news(
    item: &Value,
    story_id: &str,
    story_title: &str,
    now: DateTime<Utc>,
) -> Result<Value> {
    begin(item)?;
    let id = identifier(&item["objectID"])?;
    if !id.bytes().all(|b| b.is_ascii_digit())
        || story_id.is_empty()
        || !story_id.bytes().all(|b| b.is_ascii_digit())
        || story_id.len() > 100
        || story_title.len() > 2000
    {
        return Err(invalid());
    }
    if !item["parent_id"].is_null() && identifier(&item["parent_id"])? != story_id {
        return Err(invalid());
    }
    static TAGS: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"<[^>]+>").unwrap());
    let plain = TAGS
        .replace_all(string(item, "comment_text")?, "\n")
        .replace('\r', "&#13;");
    let mut tokenizer = html5gum::Tokenizer::new(plain.as_str());
    tokenizer.set_state(html5gum::State::RcData);
    let mut text = String::new();
    let mut count = 0usize;
    for token in tokenizer {
        count += 1;
        if count > 100000 {
            return Err(invalid());
        }
        match token.map_err(|_| invalid())? {
            html5gum::Token::String(s) => text.push_str(&String::from_utf8_lossy(&s.value)),
            html5gum::Token::Error(_) => {}
            _ => return Err(invalid()),
        }
    }
    let parts = text
        .split('\n')
        .next()
        .unwrap_or("")
        .split('|')
        .map(|s| s.trim_matches(crate::context_contract::python_space))
        .collect::<Vec<_>>();
    if parts.len() < 2 || parts[0].is_empty() || parts[1].is_empty() {
        return Err(invalid());
    }
    static SALARY: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"[$€£][\d,kK.]+(?:\s*[-–]\s*[$€£]?[\d,kK.]+)?").unwrap()
    });
    let salary = SALARY.find(&text).map(|m| m.as_str());
    let tail = parts[2..].join(" | ");
    let mut job = json!({"source_name":"hacker_news","source_job_id":id,"original_url":format!("https://news.ycombinator.com/item?id={id}"),"company_name":parts[0],"title":parts[1],"description":text,"location":parts.get(2),"remote_type":rules::remote_policy(Some(&tail)),"employment_type":rules::employment(Some(&tail)),"salary_raw":salary,"date_posted":rules::date(&item["created_at"])? ,"data_provenance":{"adapter":"HackerNewsHiringAdapter","story_id":story_id,"story_title":story_title}});
    extend(&mut job, rules::salary_fields(salary)?);
    contract::normalize(job, now)
}
