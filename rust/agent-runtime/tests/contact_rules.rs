//! Deferred actual ranking/retention comparisons. No provider/application settings imports.
use automated_apply_agents::contacts::{self, Settings, rules};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(script: &str, value: &Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut child = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(value.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn fixture() -> Value {
    json!({"contact":{"id":"11111111-1111-4111-8111-111111111111","company_id":"22222222-2222-4222-8222-222222222222","full_name":"Fictional Contact","role_title":"Engineering Manager","linkedin_url":"https://www.linkedin.com/in/fictional-contact","email":"person@example.com","email_status":"verified","confidence_score":85.0,"enrichment_source":"apollo","last_checked_at":"2026-11-16T00:00:00+00:00","last_verified_at":"2026-11-16T00:00:00+00:00","last_reviewed_at":"2026-11-16T00:00:00+00:00","do_not_contact":false,"suppression_reason":null,"human_review_notes":null,"metadata_":{"evidence_strength":"strong","job_ids":[]}},"company":{"id":"22222222-2222-4222-8222-222222222222","name":"Fictional Employer","domain":"example.com","metadata_":{"employee_count":20}},"job":null})
}
#[test]
fn saved_contact_rank_retention_and_publication_match_actual_rules_with_explicit_send_policy_override()
 {
    let mut cases = Vec::new();
    for index in 0..40 {
        let mut value = fixture();
        match index {
            0 => {}
            1 => value["contact"]["role_title"] = json!("Founder"),
            2 => {
                value["contact"]["role_title"] = json!("CTO");
                value["company"]["metadata_"]["employee_count"] = json!(500)
            }
            3 => {
                value["contact"]["role_title"] = json!("CEO");
                value["company"]["metadata_"] = json!({})
            }
            4 => value["contact"]["role_title"] = json!("Software Engineer"),
            5 => value["contact"]["do_not_contact"] = json!(true),
            6 => value["contact"]["metadata_"]["identity_review_required"] = json!(true),
            7 => value["contact"]["last_checked_at"] = json!("2026-09-01T00:00:00+00:00"),
            8 => value["contact"]["last_checked_at"] = json!("2026-01-01T00:00:00+00:00"),
            9 => value["contact"]["email_status"] = json!("provider_reported"),
            10 => value["contact"]["email"] = Value::Null,
            11 => value["contact"]["email"] = json!("jobs@example.com"),
            12 => value["contact"]["last_verified_at"] = Value::Null,
            13 => value["contact"]["last_reviewed_at"] = Value::Null,
            14 => value["contact"]["linkedin_url"] = Value::Null,
            15 => value["contact"]["metadata_"]["hiring_responsibility_confirmed"] = json!(true),
            16 => value["contact"]["metadata_"]["evidence_strength"] = json!("weak"),
            17 => value["contact"]["metadata_"]["email_observed_at"] = json!("invalid"),
            18 => {
                value["contact"]["metadata_"]["email_observed_at"] =
                    json!("2026-11-16T01:00:00+05:30")
            }
            19 => value["contact"]["metadata_"]["email_observed_at"] = json!("2026-11-16T00:00:00"),
            20 => value["contact"]["metadata_"]["email_observed_at"] = json!("2026-11-16"),
            21 => {
                value["contact"]["enrichment_source"] = json!("manual");
                value["contact"]["last_checked_at"] = json!("2026-01-01T00:00:00+00:00")
            }
            22 => {
                value["contact"]["role_title"] = json!("Founder");
                value["company"]["metadata_"] = json!({"_verified_team_size_band":"11-50"})
            }
            23 => {
                value["contact"]["role_title"] = json!("Founder");
                value["company"]["metadata_"] = json!({"employee_count":true})
            }
            24 => {
                value["contact"]["role_title"] = json!("Founder");
                value["company"]["metadata_"] = json!({"employee_count":10.0})
            }
            25 => value["contact"]["role_title"] = json!("HR recruiter"),
            26 => value["contact"]["role_title"] = json!("VP of engineering"),
            27 => {
                value["contact"]["role_title"] = json!("Campus recruiting");
                value["job"] =
                    json!({"id":"33333333-3333-4333-8333-333333333333","title":"Software intern"})
            }
            28 => {
                value["job"] = json!({"id":"33333333-3333-4333-8333-333333333333","title":"Software Engineer"});
                value["contact"]["metadata_"]["job_ids"] =
                    json!(["33333333-3333-4333-8333-333333333333"])
            }
            29 => value["contact"]["email_status"] = json!("candidate"),
            30 => value["contact"]["enrichment_source"] = Value::Null,
            31 => value["contact"]["confidence_score"] = Value::Null,
            32 => value["contact"]["last_checked_at"] = Value::Null,
            33 => value["contact"]["metadata_"]["email_observed_at"] = json!(false),
            34 => {
                value["contact"]["metadata_"]["email_observed_at"] =
                    json!("2026-01-01T00:00:00+00:00")
            }
            35 => {
                value["contact"]["metadata_"]["email_publication_confirmed"] = json!(true);
                value["contact"]["metadata_"]["email_publication_url"] =
                    json!("https://example.com/team");
                value["contact"]["metadata_"]["email_publication_digest"] =
                    json!(format!("{:x}", sha2::Sha256::digest(b"person@example.com")));
                value["contact"]["email_status"] = json!("provider_reported")
            }
            36 => value["contact"]["metadata_"]["email_publication_digest"] = json!("wrong"),
            37 => value["contact"]["metadata_"]["identity_review_required"] = json!("review"),
            38 => value["contact"]["human_review_notes"] = json!("Fictional review note"),
            _ => value["contact"]["last_checked_at"] = json!("2026-11-17T00:00:00+00:00"),
        };
        cases.push(value);
    }
    let actual = oracle(
        r#"import ast,datetime as dt,hashlib,json,re,sys
from pathlib import Path
from types import SimpleNamespace
class Frozen(dt.datetime):
 @classmethod
 def now(cls,tz=None):return cls(2026,11,17,tzinfo=dt.timezone.utc)
dt.datetime=Frozen
scope={'re':re,'hashlib':hashlib,'get_settings':lambda:SimpleNamespace(CONTACT_CACHE_TTL_DAYS=30,CONTACT_RETENTION_DAYS=90)}
def load(path,names):
 tree=ast.parse(Path(path).read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-contact>','exec'),scope)
load('backend/app/services/contact_enrichment/verification.py',{'fresh','email_observed_at','email_kind','ROLE_INBOXES'})
load('backend/app/services/contact_enrichment/ranking.py',{'rank_contact'})
load('backend/app/services/contact_read.py',{'contact_output'})
out=[]
for value in json.load(sys.stdin):
 contact=value['contact'].copy()
 for key in ('last_checked_at','last_verified_at','last_reviewed_at'):
  if contact[key] is not None:contact[key]=Frozen.fromisoformat(contact[key])
 out.append(scope['contact_output'](SimpleNamespace(**contact),SimpleNamespace(**value['company']),SimpleNamespace(**value['job']) if value['job'] else None))
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out,default=lambda value:value.isoformat()))
"#,
        &json!(cases),
    );
    let now = DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let settings = Settings {
        cache_days: 30,
        retention_days: 90,
    };
    for (index, (value, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = rules::output(
            &value["contact"],
            &value["company"],
            value["job"].as_object().map(|_| &value["job"]),
            &settings,
            now,
        )
        .unwrap();
        for (key, expected) in want.as_object().unwrap() {
            if key == "email_send_ready" {
                assert_eq!(got["email_send_ready"], false);
                assert_eq!(got["email_draft_review_ready"], *expected);
            } else {
                assert_eq!(got[key], *expected, "case {index} {key}");
            }
        }
    }
}
use sha2::Digest as _;
fn apollo_rate_fixture() -> Value {
    json!({"api/v1/people/match":{"minute":{"limit":10,"consumed":2,"left_over":8},"hour":{"limit":100,"consumed":20,"left_over":80},"day":{"limit":1000,"consumed":200,"left_over":800}}})
}
#[test]
fn apollo_endpoint_rate_metadata_matches_actual_conservative_parser() {
    use contacts::enrichment::capabilities as caps;
    let endpoint = "api/v1/people/match";
    let mut cases = Vec::new();
    for n in 0..24 {
        let mut value = apollo_rate_fixture();
        match n {
            0 => {}
            1 => {
                let row = value.as_object_mut().unwrap().remove(endpoint).unwrap();
                value["[\"api/v1/people\",\"match\"]"] = row;
            }
            2 => value["[\"api/v1/people\",\"match\"]"] = value[endpoint].clone(),
            3 => value[endpoint]["minute"]["limit"] = json!(true),
            4 => value[endpoint]["minute"]["consumed"] = json!(2.0),
            5 => value[endpoint]["minute"]["left_over"] = json!(-1),
            6 => value[endpoint]["minute"]["consumed"] = json!(11),
            7 => value[endpoint]["minute"]["left_over"] = json!(9),
            8 => {
                value[endpoint].as_object_mut().unwrap().remove("hour");
            }
            9 => value[endpoint]["day"] = Value::Null,
            10 => value[endpoint] = json!([]),
            11 => value = json!({}),
            12 => value = Value::Null,
            13 => value[endpoint]["minute"]["left_over"] = json!(0),
            14 => value[endpoint]["minute"]["limit"] = json!("10"),
            15 => {
                value[endpoint]["minute"] = json!({"limit":0,"consumed":0,"left_over":0});
            }
            16 => value[endpoint]["minute"]["consumed"] = Value::Null,
            17 => value[endpoint]["minute"]["left_over"] = json!(100),
            18 => value[endpoint]["minute"]["limit"] = json!(-1),
            19 => value["[\"other\",true]"] = json!({}),
            20 => {
                value.as_object_mut().unwrap().remove(endpoint);
                value["other"] = json!({});
            }
            21 => value[endpoint]["day"]["extra"] = json!("ignored"),
            22 => {
                let row = value.as_object_mut().unwrap().remove(endpoint).unwrap();
                value["[\"api/v1/people/match\"]"] = row;
            }
            _ => value[endpoint]["minute"]["left_over"] = json!(8.0),
        };
        cases.push(value);
    }
    let actual = oracle(
        r#"import ast,json,sys
from pathlib import Path
tree=ast.parse(Path('backend/app/services/contact_enrichment/apollo_capabilities.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'number','endpoint_limits'}];scope={'json':json};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-apollo-rates>','exec'),scope)
out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':scope['endpoint_limits'](value,'api/v1/people/match')})
 except ValueError:out.append({'ok':False})
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (value, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match caps::endpoint_limits(value, endpoint) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
#[test]
fn apollo_credit_pool_retains_actual_legacy_arithmetic_and_accepts_documented_unambiguous_wrapper()
{
    use contacts::enrichment::capabilities as caps;
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut value = json!({"lead_credit":{"limit":50,"consumed":5,"left_over":45}});
        match n {
            0 => {}
            1 => value["lead_credit"]["limit"] = json!(true),
            2 => value["lead_credit"]["consumed"] = json!(5.0),
            3 => value["lead_credit"]["left_over"] = json!(-1),
            4 => value["lead_credit"]["consumed"] = json!(51),
            5 => value["lead_credit"]["left_over"] = json!(46),
            6 => value["lead_credit"]["left_over"] = json!(0),
            7 => value["lead_credit"] = json!([]),
            8 => value = json!({}),
            9 => value = Value::Null,
            10 => value["lead_credit"]["limit"] = json!("50"),
            11 => value["lead_credit"] = json!({"limit":0,"consumed":0,"left_over":0}),
            12 => value["unrelated_pool"] = json!({"limit":500,"consumed":0,"left_over":500}),
            13 => value["lead_credit"]["extra"] = json!(999),
            14 => value["lead_credit"]["left_over"] = json!(50),
            _ => value["lead_credit"]["left_over"] = Value::Null,
        };
        cases.push(value);
    }
    let actual = oracle(
        r#"import ast,json,sys
from pathlib import Path
tree=ast.parse(Path('backend/app/services/contact_enrichment/apollo_capabilities.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'number','credit_balance'}];scope={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-apollo-credits>','exec'),scope)
out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':scope['credit_balance'](value,'lead_credit')})
 except ValueError:out.append({'ok':False})
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (value, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match caps::credit_balance(value, "lead_credit") {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
    let wrapped = json!({"credit_usage_stats":cases[0],"current_credit_cycle":{"start_date":"2026-11-01T00:00:00Z","end_date":"2026-12-01T00:00:00Z"}});
    assert_eq!(
        caps::credit_balance(&wrapped, "lead_credit").unwrap(),
        caps::credit_balance(&cases[0], "lead_credit").unwrap()
    );
    for value in [
        json!({"credit_usage_stats":cases[0],"lead_credit":cases[0]["lead_credit"]}),
        json!({"credit_usage_stats":[]}),
        json!({"credit_usage_stats":{"other_pool":cases[0]["lead_credit"]}}),
    ] {
        assert!(caps::credit_balance(&value, "lead_credit").is_err());
    }
}
#[test]
fn apollo_eligibility_matches_actual_time_and_endpoint_rules_and_preflight_confers_no_lookup_grant()
{
    use contacts::enrichment::capabilities::{self as caps, Operation};
    let now = DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let base = json!({"APOLLO_FREE_ACCOUNT_CONFIRMED":true,"APOLLO_WORK_EMAIL_CONFIRMED":true,"APOLLO_ELIGIBILITY_REVIEWED_AT":"2026-11-16T23:00:00Z","APOLLO_ELIGIBILITY_EVIDENCE_URL":"https://contact-fixture.example/review","APOLLO_REVIEWED_ENDPOINTS":["api/v1/people/match"],"APOLLO_CREDIT_POOL":"lead_credit"});
    let mut cases = Vec::new();
    for n in 0..12 {
        let mut value = base.clone();
        match n {
            0 => {}
            1 => value["APOLLO_FREE_ACCOUNT_CONFIRMED"] = json!(false),
            2 => value["APOLLO_WORK_EMAIL_CONFIRMED"] = json!(false),
            3 => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = Value::Null,
            4 => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = json!("2026-11-15T23:00:00Z"),
            5 => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = json!("2026-11-17T00:00:01Z"),
            6 => value["APOLLO_REVIEWED_ENDPOINTS"] = json!([]),
            7 => value["APOLLO_ELIGIBILITY_EVIDENCE_URL"] = Value::Null,
            8 => value["APOLLO_REVIEWED_ENDPOINTS"] = json!(["api/v1/mixed_people/api_search"]),
            9 => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = json!("2026-11-17T04:30:00+05:30"),
            10 => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = json!("2026-11-16T23:00:00"),
            _ => value["APOLLO_ELIGIBILITY_REVIEWED_AT"] = json!("2026-11-16T00:00:00Z"),
        };
        cases.push(value);
    }
    let actual = oracle(
        r#"import ast,datetime as dt,json,sys
from pathlib import Path
from types import SimpleNamespace
class Frozen(dt.datetime):
 @classmethod
 def now(cls,tz=None):return cls(2026,11,17,tzinfo=dt.timezone.utc)
class ProviderError(Exception):pass
scope={'datetime':Frozen,'timedelta':dt.timedelta,'timezone':dt.timezone,'ProviderError':ProviderError,'State':SimpleNamespace(AUTHORIZATION_REQUIRED='authorization_required')}
tree=ast.parse(Path('backend/app/services/contact_enrichment/apollo_capabilities.py').read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name=='eligibility') or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ENDPOINTS' for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-apollo-eligibility>','exec'),scope)
out=[]
for value in json.load(sys.stdin):
 if value['APOLLO_ELIGIBILITY_REVIEWED_AT']:value['APOLLO_ELIGIBILITY_REVIEWED_AT']=Frozen.fromisoformat(value['APOLLO_ELIGIBILITY_REVIEWED_AT'])
 try:scope['eligibility'](SimpleNamespace(**value),'enrich_person');out.append(True)
 except ProviderError:out.append(False)
print(json.dumps(out))
"#,
        &json!(cases),
    );
    let values = |v: &Value| {
        v.as_object()
            .unwrap()
            .iter()
            .filter(|(_, v)| !v.is_null())
            .map(|(k, v)| {
                (
                    k.clone(),
                    v.as_str()
                        .map(str::to_owned)
                        .unwrap_or_else(|| v.to_string()),
                )
            })
            .collect::<std::collections::BTreeMap<_, _>>()
    };
    for (index, (value, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let eligibility = caps::Eligibility::from_values(&values(value)).unwrap();
        assert_eq!(
            json!(eligibility.require(Operation::Enrich, now).is_ok()),
            *want,
            "case {index}"
        );
    }
    let eligibility = caps::Eligibility::from_values(&values(&base)).unwrap();
    let health = json!({"healthy":true,"is_logged_in":true});
    let credits =
        json!({"credit_usage_stats":{"lead_credit":{"limit":50,"consumed":5,"left_over":45}}});
    let finding = caps::preflight(
        &eligibility,
        Operation::Enrich,
        &health,
        &apollo_rate_fixture(),
        &credits,
        2,
        now,
    )
    .unwrap();
    assert_eq!(finding["lookup_authorized"], false);
    assert_eq!(finding["provider_requests_performed"], 0);
    assert!(
        caps::preflight(
            &eligibility,
            Operation::Enrich,
            &json!({"healthy":false}),
            &apollo_rate_fixture(),
            &credits,
            2,
            now
        )
        .is_err()
    );
    assert_eq!(
        caps::preflight(
            &eligibility,
            Operation::Enrich,
            &health,
            &apollo_rate_fixture(),
            &credits,
            46,
            now
        )
        .unwrap_err(),
        automated_apply_agents::Failure("contact_provider_budget_exhausted")
    );
}
#[test]
fn contact_enrichment_request_matches_actual_dto_defaults_and_bounded_authorization_flags() {
    let cases = json!([
        {},{"target_roles":[" CTO ","engineering_manager"]},{"target_roles":[]},{"target_roles":null},
        {"target_roles":[""]},{"target_roles":["x".repeat(256)]},{"target_roles":vec!["role";21]},
        {"max_people":1},{"max_people":25},{"max_people":26},{"max_people":0},{"max_people":"5"},
        {"max_people":5.0},{"max_people":5.5},{"max_people":true},{"providers":[]},
        {"providers":["apollo","signalhire"]},{"providers":["apollo","apollo"]},{"providers":["other"]},
        {"allow_paid":"YES"},{"allow_paid":true},{"allow_paid":null},{"allow_paid":2},
        {"allow_fallback":"off","include_candidates":1},{"idempotency_key":"fictional_123-key"},
        {"idempotency_key":"bad key"},{"idempotency_key":"x".repeat(101)},{"unexpected":true},null
    ]);
    let actual = oracle(
        r#"import json,runpy,sys
model=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']()['contact-enrichment']
out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':model.model_validate(value).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &cases,
    );
    for (index, (input, want)) in cases
        .as_array()
        .unwrap()
        .iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        let got = match contacts::enrichment::contract::normalize(input.clone()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
#[test]
fn contact_local_first_role_lookup_and_fallback_decisions_match_actual_functions() {
    let now = DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut lookup = Vec::new();
    for n in 0..12 {
        let mut c = fixture()["contact"].clone();
        c["human_corrected"] = json!(false);
        match n {
            0 => {}
            1 => c["do_not_contact"] = json!(true),
            2 => c["human_corrected"] = json!(true),
            3 => c["metadata_"]["identity_review_required"] = json!(true),
            4 => c["last_checked_at"] = json!("2026-01-01T00:00:00Z"),
            5 => {
                c["email"] = Value::Null;
                c["linkedin_url"] = Value::Null;
            }
            6 => {
                c["email_status"] = json!("candidate");
                c["metadata_"]["evidence_strength"] = json!("weak");
            }
            7 => c["metadata_"]["email_observed_at"] = json!("invalid"),
            8 => {
                c["email"] = Value::Null;
                c["metadata_"]["evidence_strength"] = json!("strong");
            }
            9 => {
                c["email"] = Value::Null;
                c["metadata_"]["evidence_strength"] = json!("moderate");
            }
            10 => c["last_checked_at"] = Value::Null,
            _ => c["email_status"] = json!("provider_reported"),
        };
        lookup.push(c);
    }
    let roles = json!([
        ["Chief Technology Officer", ["cto"]],
        ["CEO", ["ceo"]],
        ["Human Resources Manager", ["hr"]],
        ["Talent acquisition lead", ["recruiter"]],
        ["Engineering-manager", ["engineering_manager"]],
        ["Rust Developer", ["cto"]],
        [null, []],
        ["Recruiting Coordinator", ["recruiter"]],
        ["Founder", ["ceo", "founder"]],
        ["CHIEF TECHNOLOGY OFFICER", ["cto"]],
        ["Straße Engineer", ["strasse"]],
        [null, ["cto"]]
    ]);
    let mut fallback = Vec::new();
    for status in ["completed", "not_found", "billing_uncertain", "failed"] {
        for entries in [
            json!([]),
            json!([{"email":null}]),
            json!([{"email":"person@example.com"}]),
        ] {
            for allow in [false, true] {
                for identifier in [false, true] {
                    fallback.push(json!({"status":status,"contacts":entries,"allow":allow,"identifier":identifier}));
                }
            }
        }
    }
    let actual = oracle(
        r#"import ast,datetime as dt,json,sys
from pathlib import Path
from types import SimpleNamespace
class Frozen(dt.datetime):
 @classmethod
 def now(cls,tz=None):return cls(2026,11,17,tzinfo=dt.timezone.utc)
dt.datetime=Frozen
scope={'State':SimpleNamespace(COMPLETED='completed')}
def load(path,names):
 tree=ast.parse(Path(path).read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-local-first>','exec'),scope)
load('backend/app/services/contact_enrichment/verification.py',{'fresh','email_observed_at'})
load('backend/app/services/contact_enrichment/service.py',{'role_matches'})
load('backend/app/services/contact_enrichment/waterfall.py',{'RELIABLE_STATUSES','needs_lookup','fallback_justified'})
value=json.load(sys.stdin);lookup=[]
for contact in value['lookup']:
 if contact['last_checked_at']:contact['last_checked_at']=Frozen.fromisoformat(contact['last_checked_at'])
 lookup.append(scope['needs_lookup'](SimpleNamespace(**contact),30))
fallback=[]
for row in value['fallback']:
 prior=SimpleNamespace(status=row['status'],contacts=[SimpleNamespace(**c) for c in row['contacts']]);fallback.append(scope['fallback_justified'](prior,row['allow'],row['identifier']))
print(json.dumps({'lookup':lookup,'roles':[scope['role_matches'](*row) for row in value['roles']],'fallback':fallback}))
"#,
        &json!({"lookup":lookup,"roles":roles,"fallback":fallback}),
    );
    for (c, want) in lookup.iter().zip(actual["lookup"].as_array().unwrap()) {
        assert_eq!(
            json!(contacts::enrichment::policy::needs_lookup(c, 30, now)),
            *want
        );
    }
    for (c, want) in roles
        .as_array()
        .unwrap()
        .iter()
        .zip(actual["roles"].as_array().unwrap())
    {
        assert_eq!(
            json!(contacts::enrichment::policy::role_matches(
                c[0].as_str(),
                c[1].as_array().unwrap()
            )),
            *want
        );
    }
    for (c, want) in fallback.iter().zip(actual["fallback"].as_array().unwrap()) {
        assert_eq!(
            json!(contacts::enrichment::policy::fallback_justified(
                c,
                c["allow"].as_bool().unwrap(),
                c["identifier"].as_bool().unwrap()
            )),
            *want
        );
    }
}
#[test]
fn contact_correction_normalization_matches_actual_dto_preserving_null_and_omission() {
    let cases = json!([
        {}, {"full_name":"  Fictional Person  "},{"role_title":"\u{1c} CTO \u{1f}"},
        {"full_name":null},{"role_title":null},{"company_id":null},{"do_not_contact":null},
        {"email_status":null},{"verification_evidence_id":null},{"human_review_notes":null},
        {"suppression_reason":null},{"do_not_contact":true},{"do_not_contact":false},
        {"do_not_contact":"YES"},{"do_not_contact":"off"},{"do_not_contact":1},
        {"do_not_contact":0.0},{"do_not_contact":2},{"do_not_contact":"unknown"},
        {"full_name":""},{"full_name":"   "},{"full_name":123},{"role_title":"x".repeat(256)},
        {"human_review_notes":"x".repeat(4001)},{"suppression_reason":"x".repeat(1001)},
        {"email_status":"verified"},{"email_status":"provider_reported"},{"email_status":"candidate"},
        {"email_status":"unknown"},{"email_status":"invalid"},{"email_status":"guessed"},
        {"company_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
        {"verification_evidence_id":"11111111-1111-4111-8111-111111111111"},
        {"company_id":"wrong"},{"email":"unapproved-field@example.com"},null
    ]);
    let actual = oracle(
        r#"import json,runpy,sys
model=runpy.run_path('rust/scripts/export_contact_contracts.py')['model']()
out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':model.model_validate(value).model_dump(mode='json',exclude_unset=True)})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &cases,
    );
    for (index, (input, want)) in cases
        .as_array()
        .unwrap()
        .iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        match contacts::contract::normalize(input.clone()) {
            Ok(value) => assert_eq!(json!({"ok":true,"value":value}), *want, "case {index}"),
            Err(_) => assert_eq!(json!({"ok":false}), *want, "case {index}"),
        }
    }
}
#[test]
fn contact_business_mailbox_categories_match_actual_lowercase_rules_and_uppercase_role_inboxes_are_conservative()
 {
    let cases = json!([
        ["person@example.com", "example.com"],
        ["person@other.example", "example.com"],
        ["person@example.com", "https://www.example.com/team"],
        ["person@example.com", "http://example.com"],
        ["person+tag@example.com", "example.com"],
        ["hr@example.com", "example.com"],
        ["jobs.team@example.com", "example.com"],
        ["invalid", "example.com"],
        ["person@example.com ", "example.com"],
        ["person@sub.example.com", "example.com"],
        ["hello@example.com", "example.com"],
        ["recruiting-team@example.com", "example.com"],
        ["person@example.com", "www.example.com"],
        ["person@example.com", "https://OTHER.example"],
        ["no-reply@example.com", "example.com"],
        ["contact@example.com", "example.com"]
    ]);
    let actual = oracle(
        r#"import ast,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
tree=ast.parse(Path('backend/app/services/contact_enrichment/verification.py').read_text());names={'ROLE_INBOXES','domain','business_email','email_kind'};nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets))];scope={'re':re,'urlsplit':urlsplit};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-contact-email>','exec'),scope)
print(json.dumps([[scope['business_email'](email,domain),scope['email_kind'](email)] for email,domain in json.load(sys.stdin)]))
"#,
        &cases,
    );
    for (case, want) in cases
        .as_array()
        .unwrap()
        .iter()
        .zip(actual.as_array().unwrap())
    {
        let email = case[0].as_str().unwrap();
        assert_eq!(
            json!([
                rules::business_email(email, case[1].as_str().unwrap()),
                rules::email_kind(email)
            ]),
            *want
        );
    }
    for email in [
        "HR@example.com",
        "Jobs.team@example.com",
        "CAREERS+tag@example.com",
    ] {
        assert_eq!(rules::email_kind(email), "role_based");
    }
}
#[test]
fn contact_queries_settings_and_malformed_saved_metadata_are_bounded() {
    let route = contacts::Route::Company(uuid::Uuid::nil());
    for query in [
        "limit=101",
        "offset=-1",
        "limit=1&limit=2",
        "provider=unknown",
        "min_evidence_strength=maybe",
        "suppressed=perhaps",
        "email_status=guessed",
        "other=1",
    ] {
        assert!(
            contacts::Page::parse(route, Some(query)).is_err(),
            "{query}"
        );
    }
    let page = contacts::Page::parse(
        route,
        Some(
            "limit=100&offset=9&role=CTO&suppressed=false&provider=apollo&has_business_email=true",
        ),
    )
    .unwrap();
    assert_eq!((page.limit, page.offset), (100, 9));
    assert!(
        contacts::Page::parse(
            contacts::Route::Recommended(uuid::Uuid::nil()),
            Some("limit=26")
        )
        .is_err()
    );
    assert!(
        contacts::Page::parse(contacts::Route::Detail(uuid::Uuid::nil()), Some("limit=1")).is_err()
    );
    let value = fixture();
    let mut contact = value["contact"].clone();
    contact["_metadata_invalid"] = json!(true);
    assert!(
        rules::output(
            &contact,
            &value["company"],
            None,
            &Settings {
                cache_days: 30,
                retention_days: 90
            },
            Utc::now()
        )
        .is_err()
    );
}
