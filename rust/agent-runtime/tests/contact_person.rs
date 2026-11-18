//! Deferred actual DTO/provider projections. All source data and transports are fictional.
use automated_apply_agents::contacts::enrichment::person::{self, Kind};
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
#[test]
fn contact_person_observation_matches_actual_default_url_uuid_datetime_and_claim_contract() {
    let base = json!({"full_name":"Fictional Person","source":"apollo"});
    let mut cases = Vec::new();
    for n in 0..32 {
        let mut value = base.clone();
        match n {
            0 => {}
            1 => value["full_name"] = json!("  Fictional Person  "),
            2 => value["role_title"] = json!("  CTO  "),
            3 => value["full_name"] = json!(""),
            4 => value["source"] = json!("  "),
            5 => value["full_name"] = json!(123),
            6 => value["full_name"] = json!("x".repeat(256)),
            7 => {
                value["linkedin_url"] =
                    json!("https://linkedin.com/in/fictional-person?ref=fixture")
            }
            8 => value["linkedin_url"] = json!("https://other.example/in/person"),
            9 => value["linkedin_url"] = json!(""),
            10 => value["email"] = json!("not_a_verified_mailbox"),
            11 => value["email_status"] = json!("verified"),
            12 => value["email_status"] = json!("guessed"),
            13 => value["email_kind"] = json!("role_based"),
            14 => value["evidence_strength"] = json!("weak"),
            15 => value["evidence_strength"] = json!("certain"),
            16 => value["human_confirmed"] = json!("YES"),
            17 => value["human_confirmed"] = json!(2),
            18 => value["professional_url"] = json!("https://contact-fixture.example/team"),
            19 => value["permission_evidence_url"] = json!("http://contact-fixture.example/review"),
            20 => value["email_publication_url"] = json!("https://127.0.0.1/private"),
            21 => value["observed_at"] = json!("2026-11-16T12:34:56Z"),
            22 => value["observed_at"] = json!("2026-11-16T12:34:56"),
            23 => value["observed_at"] = json!("2026-11-16T12:34:56.123456789+05:30"),
            24 => value["observed_at"] = json!(1794832496),
            25 => value["discovered_person_id"] = json!("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            26 => value["discovered_person_id"] = json!("wrong"),
            27 => value["unexpected_vendor_payload"] = json!("private"),
            28 => value["provider_verification_claim"] = json!("x".repeat(101)),
            29 => value["company_domain"] = json!(" example.com "),
            30 => value["provider_person_id"] = json!(" id "),
            _ => value = Value::Null,
        };
        cases.push(value);
    }
    let actual = oracle(
        r#"import json,runpy,sys
model=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']()['contact-person-observation'];out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':model.model_validate(value).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match person::normalize(Kind::Observation, input.clone()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
#[test]
fn contact_provider_request_matches_actual_defaults_identifier_scope_and_ignored_unknown_fields() {
    let base = json!({"company_id":"11111111-1111-4111-8111-111111111111"});
    let mut cases = Vec::new();
    for n in 0..24 {
        let mut v = base.clone();
        match n {
            0 => {}
            1 => v["full_name"] = json!("  Fictional Person  "),
            2 => v["linkedin_url"] = json!("https://in.linkedin.com/in/fictional_person/"),
            3 => v["linkedin_url"] = json!("https://linkedin.com/company/fictional"),
            4 => v["person_id"] = json!("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            5 => v["company_id"] = json!("wrong"),
            6 => v["company_id"] = Value::Null,
            7 => v["max_people"] = json!("3"),
            8 => v["max_people"] = json!(true),
            9 => v["max_people"] = json!(26),
            10 => v["allow_paid"] = json!("yes"),
            11 => v["allow_paid"] = Value::Null,
            12 => v["target_roles"] = json!([" CTO ", "Rust Engineer"]),
            13 => v["target_roles"] = json!([""]),
            14 => v["target_roles"] = json!(vec!["role"; 21]),
            15 => v["company_domain"] = json!(" example.com "),
            16 => v["provider_person_id"] = json!(" id "),
            17 => v["unknown_private_field"] = json!("ignored"),
            18 => v["full_name"] = Value::Null,
            19 => v["max_people"] = json!(0),
            20 => v["linkedin_url"] = json!(""),
            21 => v["linkedin_url"] = Value::Null,
            22 => v["full_name"] = json!("x".repeat(256)),
            _ => v = json!({}),
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import json,runpy,sys
model=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']()['contact-provider-request'];out=[]
for value in json.load(sys.stdin):
 try:out.append({'ok':True,'value':model.model_validate(value).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match person::normalize(Kind::Request, input.clone()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
fn request() -> Value {
    json!({"company_id":"11111111-1111-4111-8111-111111111111","company_domain":"example.com","linkedin_url":"https://www.linkedin.com/in/fictional-person/"})
}

#[test]
fn identity_keys_and_unicode_fold_match_actual_resolver_source_without_service_imports() {
    use automated_apply_agents::contacts::enrichment::identity;
    let base = json!({"full_name":"Fictional Person","source":"apollo","company_domain":"example.com","email":"person@example.com","linkedin_url":"https://www.linkedin.com/in/fictional-person/","provider_person_id":"fictional-provider-id"});
    let mut cases = Vec::new();
    for n in 0..10 {
        let mut value = base.clone();
        match n {
            0 => {}
            1 => value["email"] = json!("jobs@example.com"),
            2 => value["email"] = json!("person@other.example"),
            3 => value["professional_url"] = json!("https://example.com/team/person"),
            4 => value["discovered_person_id"] = json!("11111111-1111-4111-8111-111111111111"),
            5 => value["linkedin_url"] = Value::Null,
            6 => value["provider_person_id"] = Value::Null,
            7 => value["source"] = json!("signalhire"),
            8 => value["email_kind"] = json!("inferred"),
            _ => {
                value["email"] = Value::Null;
                value["email_kind"] = json!("role_based");
            }
        }
        cases.push(value);
    }
    let folds = json!([
        "  Fictional   Person  ",
        "STRAẞE Engineer",
        "\u{1c} CTO \u{1f}",
        "ΚΟΣΜΟΣ",
        "İdentıty",
        "नाम",
        ""
    ]);
    let actual = oracle(
        r#"import ast,hashlib,json,re,runpy,sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
scope={'hashlib':hashlib,'re':re,'urlsplit':urlsplit}
def load(path,names):
 tree=ast.parse(Path(path).read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-identity>','exec'),scope)
load('backend/app/services/contact_enrichment/verification.py',{'domain','business_email','email_kind','ROLE_INBOXES'})
load('backend/app/services/contact_enrichment/contact_identity.py',{'folded'})
tree=ast.parse(Path('backend/app/services/contact_enrichment/contact_identity.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ContactIdentityResolver');method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='reconcile');body=[];active=False
for n in method.body:
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='email' for t in n.targets):active=True
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='matches' for t in n.targets):break
 if active:body.append(n)
body.append(ast.parse('result=sorted(keys)').body[0]);code=compile(ast.fix_missing_locations(ast.Module(body=body,type_ignores=[])),'<actual-identity-keys>','exec');models=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']();payload=json.load(sys.stdin);out=[]
for value in payload['cases']:
 observation=models['contact-person-observation'].model_validate(value);local=dict(scope,observation=observation,company=SimpleNamespace(domain='example.com'));exec(code,local);out.append(local['result'])
assert 'backend.app.core.config' not in sys.modules
print(json.dumps({'keys':out,'folds':[scope['folded'](s) for s in payload['folds']]}))
"#,
        &json!({"cases":cases,"folds":folds}),
    );
    for (input, want) in cases.iter().zip(actual["keys"].as_array().unwrap()) {
        let observation = person::normalize(Kind::Observation, input.clone()).unwrap();
        let email = observation["email"].as_str().and_then(|s| {
            automated_apply_agents::contacts::rules::business_email(s, "example.com")
        });
        let kind = email
            .as_deref()
            .map(automated_apply_agents::contacts::rules::email_kind)
            .unwrap_or(observation["email_kind"].as_str().unwrap());
        assert_eq!(
            json!(identity::identity_keys(&observation, email.as_deref(), kind).unwrap()),
            *want
        );
    }
    for (input, want) in folds
        .as_array()
        .unwrap()
        .iter()
        .zip(actual["folds"].as_array().unwrap())
    {
        assert_eq!(json!(identity::folded(input.as_str().unwrap())), *want);
    }
}

#[test]
fn local_candidate_patterns_match_actual_generator_and_remain_unverified() {
    let cases = json!([
        ["Fictional", "Person", "example.com", null],
        ["Fictional", "Person", "https://www.example.com/team", null],
        ["José", "Niño", "example.com", null],
        ["A", "B", "example.com", null],
        ["Fictional", "", "example.com", null],
        ["", "Person", "example.com", null],
        ["", "", "example.com", null],
        ["First-name", "O'Last", "example.com", null],
        [
            "Fictional",
            "Person",
            "example.com",
            "{first}.{last}@{domain}"
        ],
        [
            "Fictional",
            "Person",
            "example.com",
            "{first}_{last}@{domain}"
        ],
        ["Fictional", "Person", "example.com", "{unknown}@{domain}"],
        ["工程师", "姓名", "example.com", null]
    ]);
    let actual = oracle(
        r#"import ast,json,re,runpy,sys,unicodedata
from pathlib import Path
from pydantic import BaseModel,Field
from typing import Literal
scope={'BaseModel':BaseModel,'Field':Field,'Literal':Literal};tree=ast.parse(Path('backend/app/schemas/contact.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EmailCandidate'];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-candidate-dto>','exec'),scope)
scope.update(re=re,unicodedata=unicodedata);tree=ast.parse(Path('backend/app/services/email_candidate_generator.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EmailCandidateGenerator'];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-candidate-generator>','exec'),scope)
print(json.dumps([[c.model_dump(mode='json') for c in scope['EmailCandidateGenerator'].generate_candidates(*row)] for row in json.load(sys.stdin)]))
"#,
        &cases,
    );
    for (input, want) in cases
        .as_array()
        .unwrap()
        .iter()
        .zip(actual.as_array().unwrap())
    {
        let got = automated_apply_agents::contacts::enrichment::candidates::generate(
            input[0].as_str().unwrap(),
            input[1].as_str().unwrap(),
            input[2].as_str().unwrap(),
            input[3].as_str(),
        )
        .unwrap();
        assert_eq!(json!(got), *want);
        assert!(got.iter().all(|c| c["status"] == "candidate"));
    }
}
#[test]
fn apollo_observations_match_actual_projection_without_raw_personal_data_or_mailbox_verification() {
    let base = json!({"name":"Fictional Person","title":"CTO","organization":{"primary_domain":"example.com"},"linkedin_url":"https://www.linkedin.com/in/fictional-person","email":"person@example.com","id":"fictional-provider-person","email_status":"verified","phone":"PRIVATE_PHONE_CANARY","vendor_payload":"PRIVATE_VENDOR_CANARY"});
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut v = base.clone();
        match n {
            0 => {}
            1 => v["email"] = Value::Null,
            2 => v["email"] = json!("personal@other.example"),
            3 => v["organization"]["primary_domain"] = json!("other.example"),
            4 => v["organization"] = json!({"website_url":"http://www.example.com/team"}),
            5 => v["linkedin_url"] = json!("https://other.example/in/person"),
            6 => {
                v["name"] = Value::Null;
                v["first_name"] = json!("Fictional");
                v["last_name"] = json!("Person");
            }
            7 => {
                v["name"] = Value::Null;
                v["first_name"] = json!("Fictional");
                v["last_name_obfuscated"] = json!("P*****");
            }
            8 => v["email"] = json!("jobs@example.com"),
            9 => v = json!({}),
            10 => v["linkedin_url"] = Value::Null,
            11 => v["email_status"] = json!(1),
            12 => v["name"] = json!(" Fictional Person "),
            13 => v["id"] = json!(123),
            14 => v = Value::Null,
            _ => v["email_status"] = json!("unverified"),
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import ast,json,re,runpy,sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
models=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']();scope={'re':re,'urlsplit':urlsplit,'PersonObservation':models['contact-person-observation']}
tree=ast.parse(Path('backend/app/services/contact_enrichment/verification.py').read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in {'domain','business_email','email_kind'}) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROLE_INBOXES' for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-verification>','exec'),scope)
tree=ast.parse(Path('backend/app/services/contact_enrichment/providers/apollo.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef));method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='normalize');exec(compile(ast.Module(body=[method],type_ignores=[]),'<actual-apollo>','exec'),scope)
request=models['contact-provider-request'].model_validate({'company_id':'11111111-1111-4111-8111-111111111111','company_domain':'example.com','linkedin_url':'https://www.linkedin.com/in/fictional-person/'});out=[]
for value in json.load(sys.stdin):
 try:
  result=scope['normalize'](SimpleNamespace(name='apollo'),value,request);out.append({'ok':True,'value':result.model_dump(mode='json') if result else None})
 except (ValueError,TypeError,AttributeError):out.append({'ok':False})
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match person::apollo(input, &request()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
        assert!(!got.to_string().contains("PRIVATE_"));
        if let Some(v) = got["value"].as_object()
            && !v["email"].is_null()
        {
            assert_eq!(v["email_status"], "provider_reported");
        }
    }
    let mut redacted = base.clone();
    redacted["name"] = json!("Fictional P*****");
    assert!(person::apollo(&redacted, &request()).unwrap().is_none());
    assert_eq!(
        automated_apply_agents::contacts::rules::business_email(
            "person@bücher.example",
            "bücher.example"
        ),
        Some("person@bücher.example".into())
    );
}
fn signal_person() -> Value {
    json!({"fullName":"Fictional Person","experience":[{"current":true,"website":"https://www.example.com","position":"CTO"}],"social":[{"type":"li","link":"https://www.linkedin.com/in/fictional-person"}],"contacts":[{"type":"email","subType":"work","value":"person@example.com","rating":90},{"type":"phone","value":"PRIVATE_PHONE_CANARY"},{"type":"email","subType":"personal","value":"PRIVATE_PERSONAL_EMAIL_CANARY"}],"uid":"11111111111111111111111111111111","raw":"PRIVATE_VENDOR_CANARY"})
}
#[test]
fn signalhire_success_projection_matches_actual_adapter_and_conflicting_personal_data_is_not_merged()
 {
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut v = signal_person();
        match n {
            0 => {}
            1 => {
                v["contacts"] =
                    json!([{"type":"email","subType":"personal","value":"person@example.com"}])
            }
            2 => v["experience"][0]["website"] = json!("https://other.example"),
            3 => v["experience"][0]["current"] = json!(false),
            4 => v["social"] = json!([]),
            5 => v["contacts"] = json!([]),
            6 => {
                v.as_object_mut().unwrap().remove("experience");
            }
            7 => {
                v.as_object_mut().unwrap().remove("social");
            }
            8 => {
                v.as_object_mut().unwrap().remove("contacts");
            }
            9 => v["contacts"][0]["rating"] = Value::Null,
            10 => v["contacts"][0]["rating"] = json!("reported"),
            11 => v["experience"][0]["website"] = json!("http://example.com/team"),
            12 => v["contacts"][0]["value"] = json!("person@other.example"),
            13 => v["fullName"] = json!(123),
            14 => v = json!([]),
            _ => {
                v.as_object_mut().unwrap().remove("uid");
            }
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import ast,asyncio,json,re,runpy,sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from pydantic import ValidationError
models=runpy.run_path('rust/scripts/export_contact_contracts.py')['models']()
class ProviderError(Exception):pass
states={n:n.lower() for n in ('COMPLETED','NOT_FOUND','FAILED','UNSUPPORTED','QUEUED','RUNNING','BUDGET_EXHAUSTED')};scope={'re':re,'urlsplit':urlsplit,'PersonObservation':models['contact-person-observation'],'ProviderError':ProviderError,'ValidationError':ValidationError,'State':SimpleNamespace(**states)}
tree=ast.parse(Path('backend/app/services/contact_enrichment/verification.py').read_text());nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in {'domain','business_email','email_kind'}) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROLE_INBOXES' for t in n.targets))];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-verification>','exec'),scope)
tree=ast.parse(Path('backend/app/services/contact_enrichment/providers/signalhire.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef));method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='enrich_person');exec(compile(ast.Module(body=[method],type_ignores=[]),'<actual-signalhire>','exec'),scope)
request=models['contact-provider-request'].model_validate({'company_id':'11111111-1111-4111-8111-111111111111','company_domain':'example.com','linkedin_url':'https://www.linkedin.com/in/fictional-person/'})
class Fixture:
 name='signalhire'
 def __init__(self,value):self.value=value
 def authorize(self,request):pass
 async def request(self,method,path,body):return [{'item':request.linkedin_url,'status':'success','candidate':self.value}],200
 def result(self,status,**values):return {'status':status,'contacts':values.get('contacts',[])}
 def error_result(self,error):raise error
out=[]
for value in json.load(sys.stdin):
 result=asyncio.run(scope['enrich_person'](Fixture(value),request))
 out.append({'ok':result['status']!='failed','value':result['contacts'][0].model_dump(mode='json') if result['contacts'] else None} if result['status']!='failed' else {'ok':False})
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match person::signalhire(input, &request()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
        assert!(!got.to_string().contains("PRIVATE_"));
    }
    let mut conflict = signal_person();
    conflict["contacts"]
        .as_array_mut()
        .unwrap()
        .push(json!({"type":"email","subType":"work","value":"different@example.com"}));
    assert!(person::signalhire(&conflict, &request()).is_err());
    let mut conflict = signal_person();
    conflict["social"]
        .as_array_mut()
        .unwrap()
        .push(json!({"type":"li","link":"https://www.linkedin.com/in/different-person"}));
    assert!(person::signalhire(&conflict, &request()).is_err());
}
