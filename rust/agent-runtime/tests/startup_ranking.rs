//! Deferred actual company relevance weights with the real deterministic job matcher.
use automated_apply_agents::startup_catalog::{
    contract::{self, Kind},
    ranking,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn startup_relevance_matches_actual_weight_reasons_unknowns_profile_version_and_exclusions() {
    let company = json!({"name":"Fictional Company","domain":"fictional.example","metadata_":{"startup_discovery":{"stage":"seed","source":"work_at_a_startup"}}});
    let profile = json!({"version":1,"verified_skills":["Rust","Python"],"verified_experience_years":1,"preferences":{"target_titles":["Rust Engineer"],"preferred_locations":["Bengaluru"],"remote_preference":"remote","company_stages":["seed"],"excluded_companies":[],"excluded_titles":[],"excluded_keywords":[]}});
    let job = json!({"title":"Rust Engineer","description":"Rust engineering role","skills_required":["Rust"],"location":"Bengaluru","is_remote":true,"remote_type":"remote","experience_level":"junior","employment_type":"full_time","salary_min":null,"salary_max":null,"salary_currency":null,"salary_period":null,"date_posted":null});
    let mut cases = Vec::new();
    let mut native = Vec::new();
    for n in 0..32 {
        let mut p = profile.clone();
        let mut c = company.clone();
        let mut jobs = vec![job.clone()];
        let mut attrs = json!({"technology_stack":["Rust"],"stage":"seed","location":"Bengaluru","remote_policy":"remote"});
        let mut size =
            json!({"team_size_band":"11-50","team_size_evidence_status":"source_reported"});
        let mut hiring = json!({"hiring_status":"hiring_confirmed"});
        let mut contacts = vec![json!({"confidence":"supported","priority":"preferred"})];
        let mut filters = json!({});
        match n {
            0 => {}
            1 => p = Value::Null,
            2 => jobs.clear(),
            3 => {
                p = Value::Null;
                jobs.clear();
                attrs = json!({});
                size = json!({"team_size_band":"unknown","team_size_evidence_status":"team_size_unknown"});
                hiring = json!({"hiring_status":"hiring_unknown"});
                contacts.clear();
            }
            4 => attrs["technology_stack"] = json!(["Java"]),
            5 => attrs["technology_stack"] = json!([]),
            6 => p["verified_skills"] = json!([]),
            7 => filters["skills"] = json!(["Rust"]),
            8 => filters["skills"] = json!(["Python"]),
            9 => size["team_size_band"] = json!("1-10"),
            10 => size["team_size_band"] = json!("500+"),
            11 => {
                size["team_size_band"] = json!("unknown");
                size["team_size_evidence_status"] = json!("conflicting");
            }
            12 => hiring["hiring_status"] = json!("hiring_possible"),
            13 => hiring["hiring_status"] = json!("hiring_unknown"),
            14 => hiring["hiring_status"] = json!("not_currently_hiring"),
            15 => contacts.clear(),
            16 => contacts[0]["priority"] = json!("suppressed"),
            17 => contacts[0]["priority"] = json!("review_required"),
            18 => contacts[0]["confidence"] = json!("unverified"),
            19 => {
                attrs["location"] = json!("Delhi");
                attrs["remote_policy"] = json!("onsite");
                filters["remote_preference"] = json!("onsite");
            }
            20 => {
                attrs["remote_policy"] = json!("unknown");
                attrs["location"] = Value::Null;
            }
            21 => {
                filters["locations"] = json!(["Delhi"]);
                filters["remote_preference"] = json!("any");
            }
            22 => attrs["stage"] = json!("established"),
            23 => p["preferences"]["excluded_companies"] = json!(["Fictional Company"]),
            24 => p["preferences"]["excluded_titles"] = json!(["Rust"]),
            25 => p["preferences"]["excluded_keywords"] = json!(["engineering"]),
            26 => jobs[0]["skills_required"] = json!(["Java"]),
            27 => {
                jobs.push(job.clone());
                jobs[1]["title"] = json!("Unrelated role");
            }
            28 => {
                p["preferences"]["prioritize_startups"] = json!(true);
                c["metadata_"] = json!({});
            }
            29 => p["preferences"]["excluded_companies"] = json!(["fictional.example"]),
            30 => {
                p["verified_skills"] =
                    json!(["Rust", "Python", "Java", "C++", "C", "TypeScript", "SQL"]);
                attrs["technology_stack"] = json!(["Rust"]);
            }
            _ => {
                p["preferences"]["company_stages"] = json!([]);
                p["preferences"]["preferred_locations"] = json!([]);
                p["preferences"]["remote_preference"] = Value::Null;
                attrs["remote_policy"] = json!("onsite");
            }
        }
        let filters = contract::normalize(Kind::Filters, filters).unwrap();
        native.push(
            ranking::rank(
                &c,
                &jobs,
                &attrs,
                &size,
                &hiring,
                &contacts,
                if p.is_null() { None } else { Some(&p) },
                &filters,
            )
            .unwrap(),
        );
        cases.push(json!({"company":c,"jobs":jobs,"attributes":attrs,"size":size,"hiring":hiring,"contacts":contacts,"profile":p,"filters":filters}));
    }
    let script = r#"import ast,html,json,re,runpy,sys,types,uuid
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from uuid import UUID
from pydantic import BaseModel,Field
from backend.app.schemas.candidate_profile import CandidateProfileRead
runtime=runpy.run_path('rust/scripts/export_execution_contracts.py');root=runtime['ROOT'];load=runtime['load']
services=types.ModuleType('backend.app.services');services.__path__=[];sys.modules[services.__name__]=services
integrations=types.ModuleType('backend.app.integrations');integrations.__path__=[];sys.modules[integrations.__name__]=integrations
gmail=types.ModuleType('backend.app.integrations.gmail');gmail.__path__=[];sys.modules[gmail.__name__]=gmail
history=types.ModuleType('backend.app.integrations.gmail.history');history.previously_applied=lambda job,company,history:False;sys.modules[history.__name__]=history
app={'__name__':'startup_rank_application_assistant','BaseModel':BaseModel,'Field':Field,'html':html,'re':re,'uuid':uuid,'Job':object}
load(app,'backend/app/services/application_assistant.py',{'skill_key','title_key','CandidateProfile','JobMatchResult'})
tree=ast.parse((root/'backend/app/services/application_assistant.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ApplicationAssistant');cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='calculate_match'];exec(compile(ast.Module(body=[cls],type_ignores=[]),'startup_rank_application_assistant','exec'),app);app['ApplicationAssistant'].__init__=lambda self,session:None
application=types.ModuleType('backend.app.services.application_assistant');application.ApplicationAssistant=app['ApplicationAssistant'];application.CandidateProfile=app['CandidateProfile'];sys.modules[application.__name__]=application
matcher={'__name__':'startup_rank_matcher','BaseModel':BaseModel,'Field':Field,'ApplicationAssistant':app['ApplicationAssistant'],'CandidateProfile':app['CandidateProfile']};load(matcher,'backend/app/services/job_discovery_matcher.py',{'SKILL_GAP_FACTOR','DiscoveryMatch','JobDiscoveryMatcher'})
matcher_module=types.ModuleType('backend.app.services.job_discovery_matcher');matcher_module.JobDiscoveryMatcher=matcher['JobDiscoveryMatcher'];sys.modules[matcher_module.__name__]=matcher_module
scope={'__name__':'startup_rank_fixture','JobDiscoveryMatcher':matcher['JobDiscoveryMatcher']};load(scope,'backend/app/services/startup_discovery/ranking.py',{'rank_startup'})
def profile_from(data):
 return CandidateProfileRead(id=UUID(int=2),singleton_key='primary',full_name='Fictional Candidate',email='fixture@example.com',created_at=datetime(2026,11,17,tzinfo=timezone.utc),updated_at=datetime(2026,11,17,tzinfo=timezone.utc),**data)
def job_from(data):
 raw={'description':None,'location':None,'is_remote':False,'experience_level':None,'employment_type':None,'salary_min':None,'salary_max':None,'salary_currency':None,'salary_period':None,'date_posted':None,**data,'id':UUID(int=1),'job_url':'https://boards.greenhouse.io/fictional/jobs/123456','application_url':None}
 return NS(**raw)
out=[]
for case in json.load(sys.stdin):
 data=case['profile'];company=case['company'];meta=company.get('metadata_',{}).get('startup_discovery',{});employer=NS(name=company['name'],domain=company.get('domain'),metadata_={'startup_discovery':{'stage':meta.get('stage'),'source':meta.get('source')}})
 profile=profile_from(data) if data else None;jobs=[job_from(j) for j in case['jobs']]
 result=scope['rank_startup'](None,employer,jobs,case['attributes'],case['size'],case['hiring'],case['contacts'],profile,NS(**case['filters']));out.append(result)
assert 'backend.app.core.config' not in sys.modules;assert 'backend.app.services.credit_manager' not in sys.modules;print(json.dumps(out))
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut c = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin
        .take()
        .unwrap()
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let actual: Value = serde_json::from_slice(&out.stdout).unwrap();
    for (index, (a, b)) in native.iter().zip(actual.as_array().unwrap()).enumerate() {
        assert_eq!(*a, *b, "case {index}");
    }
}
#[test]
fn startup_relevance_refuses_unbounded_inputs_and_never_promotes_a_score_to_authority() {
    let filters = contract::normalize(Kind::Filters, json!({})).unwrap();
    let c = json!({"name":"Fictional Company","domain":null});
    let attrs = json!({});
    let size = json!({"team_size_band":"unknown","team_size_evidence_status":"team_size_unknown"});
    let hiring = json!({"hiring_status":"hiring_unknown"});
    let result = ranking::rank(&c, &[], &attrs, &size, &hiring, &[], None, &filters).unwrap();
    assert_eq!(result["score_kind"], "relevance_not_probability");
    assert!(result.get("application_allowed").is_none());
    assert!(result.get("email_send_ready").is_none());
    assert!(
        ranking::rank(
            &c,
            &vec![json!({}); 501],
            &attrs,
            &size,
            &hiring,
            &[],
            None,
            &filters
        )
        .is_err()
    );
}
