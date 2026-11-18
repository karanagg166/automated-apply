//! Deferred actual adapter-record comparisons; no provider clients/settings or HTTP.
use automated_apply_agents::job_sources::{records, rules};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn oracle(cases: &Value) -> Vec<Value> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,html,json,math,re,runpy,sys
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
from typing import Any,Literal
from types import SimpleNamespace
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from backend.app.core.job_urls import ats_job_url,canonical_job_url
m=runpy.run_path('rust/scripts/export_execution_contracts.py');root=m['ROOT']
s=dict(__name__='fictional_public_record',re=re,html=html,json=json,math=math,datetime=datetime,timedelta=timedelta,timezone=timezone,Any=Any,Literal=Literal,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,ats_job_url=ats_job_url,canonical_job_url=canonical_job_url,urlsplit=urlsplit)
m['load'](s,'backend/app/schemas/normalized_job.py',{'NormalizedJob'})
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
s['datetime']=Clock
m['load'](s,'backend/app/services/job_sources/normalization.py',{'parse_date','remote_policy','employment','salary_fields'})
m['load'](s,'backend/app/services/job_sources/public_ats.py',{'structured_salary','hosted_job_url'})
m['load'](s,'backend/app/services/job_sources/smartrecruiters.py',{'posting_url'})
parsers={}
for filename,names in [('direct_api.py',{'GreenhouseAdapter','RemotiveAdapter','ArbeitnowAdapter','HackerNewsHiringAdapter'}),('public_ats.py',{'LeverAdapter','AshbyAdapter'}),('smartrecruiters.py',{'SmartRecruitersAdapter'})]:
 tree=ast.parse((root/'backend/app/services/job_sources'/filename).read_text())
 for cls in tree.body:
  if not isinstance(cls,ast.ClassDef) or cls.name not in names:continue
  if cls.name in {'LeverAdapter','AshbyAdapter','SmartRecruitersAdapter'}:method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='parse')
  else:
   fetch=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='fetch_jobs')
   method=next(n for n in ast.walk(fetch) if isinstance(n,ast.FunctionDef) and n.name=='parse')
  scope=s.copy();exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_public_record','exec'),scope);parsers[cls.name]=(scope,scope['parse'])
out=[]
for c in json.load(sys.stdin):
 try:
  if c['op']=='salary':v=s['salary_fields'](c['value'])
  elif c['op']=='remote':v=s['remote_policy'](c['value'])
  elif c['op']=='employment':v=s['employment'](c['value'])
  elif c['op']=='structured':v=s['structured_salary'](*c['value'],dict(year='year',month='month',hour='hour'))
  elif c['op']=='date':
   v=s['parse_date'](c['value']);v=v.astimezone(timezone.utc).isoformat().replace('+00:00','Z') if v and v.tzinfo else v.isoformat()+'Z' if v else None
  elif c['op']=='hosted':v=s['hosted_job_url'](c['value'],'fictional','lever','jobs.lever.co',application=c['application'])
  elif c['op']=='smart':v=s['posting_url'](c['value'],'fictional','12345')
  else:
   name=c['adapter'];scope,parse=parsers[name];subject=type(name,(),{})();subject.source_name=c['source'];subject.settings=SimpleNamespace(LEVER_REGION='global');subject.boards={'fictional':'Fictional Employer'}
   subject.job_url=lambda value,board,application=False:s['hosted_job_url'](value,board,c['source'],'jobs.lever.co' if c['source']=='lever' else 'jobs.ashbyhq.com',application=application)
   scope.update(self=subject,token='fictional',company='Fictional Employer',page=1,story_id='98765',story={'title':'Ask HN: Who is hiring? (November 2026)'})
   if name in {'LeverAdapter','AshbyAdapter'}:v=parse(subject,c['value'],'fictional','Fictional Employer')
   elif name=='SmartRecruitersAdapter':v=parse(subject,c['value'],'fictional','12345')
   else:v=parse(c['value'])
   v=v.model_dump(mode='json');v['data_provenance'].pop('source_fields',None)
  out.append({'ok':True,'value':v})
 except (ValueError,TypeError,KeyError,AttributeError,OverflowError):out.append({'ok':False})
assert 'httpx' not in sys.modules
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))"#;
    let mut p = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    p.stdin
        .take()
        .unwrap()
        .write_all(cases.to_string().as_bytes())
        .unwrap();
    let output = p.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn compare(cases: Vec<Value>, actual: impl Fn(&Value) -> automated_apply_agents::Result<Value>) {
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        let value = actual(case);
        assert_eq!(
            value.is_ok(),
            expected["ok"].as_bool().unwrap(),
            "case {n}: {case}"
        );
        if let Ok(value) = value {
            assert_eq!(value, expected["value"], "case {n}: {case}");
        }
    }
}
#[test]
fn public_remote_employment_and_salary_match_actual_eighty_evidence_only_cases() {
    let texts = [
        None,
        Some(""),
        Some("Hybrid remote"),
        Some("Not remote, hybrid"),
        Some("on-site only"),
        Some("Full-time Contract"),
        Some("part time internship"),
        Some("freelance"),
        Some("\u{001c}REMOTE"),
        Some("onsite"),
    ];
    let mut cases = Vec::new();
    for value in texts {
        cases.push(json!({"op":"remote","value":value}));
        cases.push(json!({"op":"employment","value":value}));
    }
    for salary in [
        None,
        Some(""),
        Some("USD 100k - 150k per year"),
        Some("$100k-$150k/year"),
        Some("EUR 80,000 annual"),
        Some("€40/hour"),
        Some("GBP 30 /hr"),
        Some("INR 1m-2m p.a."),
        Some("usd 100k annual"),
        Some("USD 150k-100k/year"),
        Some("0.5% equity"),
        Some("CAD 1000 per week"),
        Some("AUD 5000 monthly"),
        Some("£300/day"),
        Some("USD ١٠٠k - ١٥٠k yearly"),
        Some("USD\u{001c}100 annual"),
        Some("USD 100m"),
        Some("Salary $100,000, USD"),
        Some("EUR 100-USD 200 annual"),
        Some("USD ,,, annual"),
    ] {
        cases.push(json!({"op":"salary","value":salary}));
    }
    for n in 0..40 {
        let mut v = json!([10, 20, "USD", "year"]);
        match n % 10 {
            0 => {}
            1 => v[0] = Value::Null,
            2 => v[1] = Value::Null,
            3 => v[0] = json!(true),
            4 => v[0] = json!("10"),
            5 => v[1] = json!(1),
            6 => v[2] = json!("usd"),
            7 => v[3] = json!("fortnight"),
            8 => v[0] = json!(-1),
            9 => v[0] = json!(1000000000001i64),
            _ => unreachable!(),
        }
        if n >= 20 {
            v[3] = json!(if n % 2 == 0 { "hour" } else { "month" });
        }
        cases.push(json!({"op":"structured","value":v}));
    }
    compare(cases, |c| {
        Ok(match c["op"].as_str().unwrap() {
            "remote" => json!(rules::remote_policy(c["value"].as_str())),
            "employment" => json!(rules::employment(c["value"].as_str())),
            "salary" => rules::salary_fields(c["value"].as_str())?,
            "structured" => rules::structured_salary(
                &c["value"][0],
                &c["value"][1],
                &c["value"][2],
                &c["value"][3],
                &[("year", "year"), ("month", "month"), ("hour", "hour")],
            ),
            _ => unreachable!(),
        })
    });
}
#[test]
fn actual_hosted_url_rules_bind_employer_posting_and_application_without_fetching() {
    let mut cases = Vec::new();
    for value in [
        "https://jobs.lever.co/fictional/abcdefghij-12345",
        "https://jobs.lever.co/FICTIONAL/abcdefghij-12345/",
        "https://jobs.lever.co/fictional/abcdefghij-12345/apply",
        "https://jobs.lever.co/other/abcdefghij-12345",
        "https://jobs.lever.co/fictional/abcdefghij-12345?query=x",
        "https://jobs.lever.co/fictional/abcdefghij-12345#fragment",
        "https://JOBS.LEVER.CO/fictional/abcdefghij-12345",
        "http://jobs.lever.co/fictional/abcdefghij-12345",
        "https://jobs.lever.co/fictional/invalid_id",
        "https://jobs.lever.co/fictional/abcdefghij-12345/application",
    ] {
        for application in [false, true] {
            cases.push(json!({"op":"hosted","value":value,"application":application}));
        }
    }
    for value in [
        "https://jobs.smartrecruiters.com/fictional/12345",
        "https://jobs.smartrecruiters.com/FICTIONAL/12345-role-name/",
        "https://jobs.smartrecruiters.com/fictional/12345?oga=true",
        "https://jobs.smartrecruiters.com/other/12345",
        "https://jobs.smartrecruiters.com/fictional/123456",
        "https://jobs.smartrecruiters.com/fictional/12345-",
        "https://jobs.smartrecruiters.com/fictional/12345?token=private",
        "https://jobs.smartrecruiters.com/fictional/12345#part",
    ] {
        cases.push(json!({"op":"smart","value":value}));
    }
    compare(cases, |c| {
        let raw = c["value"].as_str().unwrap();
        if c["op"] == "hosted" {
            rules::hosted_url(
                raw,
                "fictional",
                "lever",
                "global",
                c["application"].as_bool().unwrap(),
            )
            .map(|v| json!(v))
        } else {
            rules::smart_url(raw, "fictional", "12345").map(|v| json!(v))
        }
    });
}
fn fixture(source: &str) -> Value {
    match source {
        "greenhouse" => {
            json!({"id":12345,"absolute_url":"https://boards.greenhouse.io/fictional/jobs/12345","title":"Fictional Engineer","content":"Public role description","location":{"name":"Remote"},"first_published":"2026-11-01T00:00:00Z","updated_at":"2026-11-02T00:00:00Z"})
        }
        "remotive" => {
            json!({"id":12345,"url":"https://remotive.com/remote-jobs/fictional-engineer","title":"Fictional Engineer","description":"Public role description","company_name":"Fictional Employer","candidate_required_location":"Worldwide","job_type":"full_time","salary":"USD 100k-150k annual","tags":["Rust"],"publication_date":"2026-11-01T00:00:00Z"})
        }
        "arbeitnow" => {
            json!({"slug":"fictional-engineer","url":"https://www.arbeitnow.com/jobs/fictional-engineer","title":"Fictional Engineer","description":"Public role description","company_name":"Fictional Employer","location":"Remote","remote":false,"tags":["Senior"],"job_types":["full time"],"created_at":1793491200})
        }
        "lever" => {
            json!({"id":"abcdefghij-12345","hostedUrl":"https://jobs.lever.co/fictional/abcdefghij-12345","applyUrl":"https://jobs.lever.co/fictional/abcdefghij-12345/apply","text":"Fictional Engineer","descriptionPlain":"Public role description","categories":{"location":"Remote","commitment":"Full-time"},"workplaceType":"remote","salaryRange":{"min":100000,"max":150000,"currency":"USD","interval":"per-year-salary"},"salaryDescriptionPlain":"USD 100k-150k annual"})
        }
        "ashby" => {
            json!({"isListed":true,"jobUrl":"https://jobs.ashbyhq.com/fictional/abcdefghij-12345","applyUrl":"https://jobs.ashbyhq.com/fictional/abcdefghij-12345/application","title":"Fictional Engineer","descriptionPlain":"Public role description","location":"Remote","workplaceType":"Hybrid","isRemote":true,"employmentType":"FullTime","publishedAt":"2026-11-01T00:00:00Z","compensation":{"scrapeableCompensationSalarySummary":"USD 100k-150k annual","summaryComponents":[{"compensationType":"Salary","minValue":100000,"maxValue":150000,"currencyCode":"USD","interval":"1 YEAR"}]}})
        }
        "smartrecruiters" => {
            json!({"id":"12345","active":true,"company":{"identifier":"fictional"},"postingUrl":"https://jobs.smartrecruiters.com/fictional/12345-role","applyUrl":"https://jobs.smartrecruiters.com/fictional/12345-role?oga=true","name":"Fictional Engineer","location":{"city":"Remote","country":"US","remote":false},"typeOfEmployment":{"label":"Full-time"},"experienceLevel":{"label":"Mid"},"releasedDate":"2026-11-01T00:00:00Z","jobAd":{"sections":{"jobDescription":{"text":"Public role description"},"qualifications":{"text":"Rust experience"}}}})
        }
        "hacker_news" => {
            json!({"objectID":"12345","parent_id":98765,"comment_text":"Fictional Employer | Fictional Engineer | Remote | Full-time\nPublic role description &amp; tooling","created_at":"2026-11-01T00:00:00Z"})
        }
        _ => unreachable!(),
    }
}
#[test]
fn seven_actual_provider_parsers_match_eighty_four_selected_records_without_raw_vendor_json() {
    let mut cases = Vec::new();
    for (source, adapter, title, url, date) in [
        (
            "greenhouse",
            "GreenhouseAdapter",
            "title",
            "absolute_url",
            "first_published",
        ),
        (
            "remotive",
            "RemotiveAdapter",
            "title",
            "url",
            "publication_date",
        ),
        (
            "arbeitnow",
            "ArbeitnowAdapter",
            "title",
            "url",
            "created_at",
        ),
        ("lever", "LeverAdapter", "text", "hostedUrl", "unused"),
        ("ashby", "AshbyAdapter", "title", "jobUrl", "publishedAt"),
        (
            "smartrecruiters",
            "SmartRecruitersAdapter",
            "name",
            "postingUrl",
            "releasedDate",
        ),
        (
            "hacker_news",
            "HackerNewsHiringAdapter",
            "unused",
            "unused",
            "created_at",
        ),
    ] {
        for n in 0..12 {
            let mut v = fixture(source);
            match n {
                0 => {}
                1 => {
                    if source == "hacker_news" {
                        v["comment_text"] = json!("incomplete");
                    } else {
                        v[title] = json!("");
                    }
                }
                2 => {
                    if source == "hacker_news" {
                        v["parent_id"] = json!(99999);
                    } else {
                        v[url] = json!("http://invalid-fixture.example/private");
                    }
                }
                3 => {
                    if source == "lever" {
                        v["applyUrl"] = json!("https://jobs.lever.co/other/abcdefghij-12345/apply");
                    } else {
                        v[date] = json!("invalid-date");
                    }
                }
                4 => {
                    if source == "hacker_news" {
                        v["objectID"] = json!("not-numeric");
                    } else if source == "ashby" {
                        v["isListed"] = json!(false);
                    } else if source == "smartrecruiters" {
                        v["active"] = json!(false);
                    } else if source == "arbeitnow" {
                        v["slug"] = json!(true);
                    } else {
                        v["id"] = Value::Null;
                    }
                }
                5 => {
                    v["location"] = json!({"name":"Hybrid onsite","remote":true});
                    if source == "arbeitnow" || source == "ashby" {
                        v["location"] = json!("Hybrid");
                    }
                    if source == "lever" {
                        v["workplaceType"] = json!("hybrid");
                    }
                    if source == "remotive" {
                        v["candidate_required_location"] = json!("Europe");
                    }
                }
                6 => {
                    if source == "hacker_news" {
                        v["comment_text"] = json!(
                            "Fictional Employer | Fictional Engineer | On-site only\nUSD 100k annual"
                        );
                    } else {
                        v["salary"] = json!("$100k-150k/year");
                        v["salaryRange"] = json!({"min":true,"max":200,"currency":"USD","interval":"per-year-salary"});
                    }
                }
                7 => {
                    if source == "ashby" {
                        v["workplaceType"] = json!("OnSite");
                        v["isRemote"] = json!(true);
                    } else if source == "smartrecruiters" {
                        v["company"]["identifier"] = json!("other");
                    } else if source == "lever" {
                        v["categories"] = json!(1);
                    } else if source == "hacker_news" {
                        v["comment_text"] =
                            json!("Fictional &amp; Employer | Engineer | Remote<p>Body&#13;\nmore");
                    } else {
                        v["description"] = json!("  Public changed description  ");
                        v["content"] = json!("  Public changed description  ");
                    }
                }
                8 => {
                    if source == "lever" {
                        v["id"] = json!("different-id");
                    } else if source == "ashby" {
                        v["applyUrl"] =
                            json!("https://jobs.ashbyhq.com/fictional/different-id/application");
                    } else if source == "smartrecruiters" {
                        v["id"] = json!("99999");
                    } else if source == "arbeitnow" {
                        v["remote"] = json!(true);
                    } else {
                        v["company_name"] = Value::Null;
                    }
                }
                9 => {
                    if source == "ashby" {
                        v["publishedAt"] = json!(1793491200);
                    } else if source == "smartrecruiters" {
                        v["releasedDate"] = json!(1793491200);
                    } else if source == "lever" {
                        v["salaryRange"]["max"] = json!(1);
                    } else if source == "hacker_news" {
                        v["comment_text"] =
                            json!("Fictional Employer | Engineer | Hybrid\n$100k-$150k");
                    } else {
                        v["company_name"] = json!("Changed Fictional Employer");
                    }
                }
                10 => {
                    v["recruiter_email"] = json!("PRIVATE_PROVIDER_PERSON_CANARY");
                    v["private_token"] = json!("PRIVATE_PROVIDER_TOKEN_CANARY");
                }
                11 => {
                    if matches!(source, "ashby" | "lever") {
                        v.as_object_mut().unwrap().remove("workplaceType");
                    } else if source == "smartrecruiters" {
                        v["jobAd"]["sections"]["additionalInformation"] =
                            json!({"text":"More public context"});
                    } else if source == "hacker_news" {
                        v["comment_text"] =
                            json!("Fictional Employer | Engineer | not remote\nPublic description");
                    } else {
                        v["job_type"] = json!("contract");
                    }
                }
                _ => unreachable!(),
            }
            cases.push(json!({"op":"record","source":source,"adapter":adapter,"value":v}));
        }
    }
    compare(cases, |c| {
        let item = &c["value"];
        let value = match c["source"].as_str().unwrap() {
            "greenhouse" => records::greenhouse(item, "fictional", "Fictional Employer", now()),
            "remotive" => records::remotive(item, now()),
            "arbeitnow" => records::arbeitnow(item, 1, now()),
            "lever" => records::lever(item, "fictional", "Fictional Employer", "global", now()),
            "ashby" => records::ashby(item, "fictional", "Fictional Employer", now()),
            "smartrecruiters" => {
                records::smartrecruiters(item, "fictional", "Fictional Employer", "12345", now())
            }
            "hacker_news" => records::hacker_news(
                item,
                "98765",
                "Ask HN: Who is hiring? (November 2026)",
                now(),
            ),
            _ => unreachable!(),
        }?;
        assert!(!value.to_string().contains("CANARY"));
        assert!(value["data_provenance"].get("source_fields").is_none());
        Ok(value)
    });
}
#[test]
fn parser_bounds_refuse_oversized_and_unattributed_or_private_evidence_before_ingestion() {
    let mut value = fixture("remotive");
    value["description"] = json!("x".repeat(1048577));
    assert!(records::remotive(&value, now()).is_err());
    let mut value = fixture("greenhouse");
    value["id"] = json!(true);
    assert!(records::greenhouse(&value, "fictional", "Fictional Employer", now()).is_err());
    let mut value = fixture("ashby");
    value["isRemote"] = json!("true");
    assert!(records::ashby(&value, "fictional", "Fictional Employer", now()).is_err());
    assert!(records::arbeitnow(&fixture("arbeitnow"), 101, now()).is_err());
}
#[test]
fn provider_dates_match_actual_twenty_four_seconds_and_iso_evidence_cases() {
    let values = json!([
        null,
        "",
        1793491200,
        1793491200.125,
        0,
        -1,
        -2208988800i64,
        1793491200000i64,
        "2026-11-01T00:00:00Z",
        "2026-11-01T05:30:00+05:30",
        "2026-11-01T00:00:00",
        "2026-11-01 12:30:00",
        "2026-11-01",
        "20261101",
        "2026-11-01T00:00:00.123456Z",
        "invalid",
        true,
        false,
        "1793491200",
        "2026-13-01",
        "2026-11-31",
        "2026-11-01T24:00:00Z",
        {},
        [1793491200]
    ]);
    let cases = values
        .as_array()
        .unwrap()
        .iter()
        .map(|v| json!({"op":"date","value":v}))
        .collect();
    compare(cases, |c| rules::date(&c["value"]));
}
