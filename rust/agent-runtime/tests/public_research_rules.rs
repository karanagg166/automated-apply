//! Deferred actual search-index/name/role/ambiguity comparisons. No network or credentials.
use automated_apply_agents::people_research::rules;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-15T12:00:00Z")
        .unwrap()
        .to_utc()
}
fn oracle(cases: Value) -> Value {
    let script = r#"import ast,asyncio,json,runpy,sys,types
from datetime import datetime,timezone
from enum import StrEnum
from types import SimpleNamespace
module=runpy.run_path('rust/scripts/export_people_contracts.py');models=module['models']();load=module['load'];root=module['ROOT']
scope={'__name__':'actual_pure_search','PublicPerson':models['public-person'],'StrEnum':StrEnum,'httpx':SimpleNamespace(HTTPError=RuntimeError)}
load(scope,'backend/app/schemas/discovery.py',{'DiscoveryStatus','DiscoveryError'});scope['Status']=scope['DiscoveryStatus']
load(scope,'backend/app/services/people_discovery/public_search.py',{'ROLE_PATTERNS'})
tree=ast.parse((root/'backend/app/services/people_discovery/public_search.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef));cls.body=[n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'__init__','search','search_official'}];exec(compile(ast.Module(body=[cls],type_ignores=[]),'actual_pure_search','exec'),scope)
base=types.ModuleType('backend.app.services.people_discovery.base');base.OfficialPersonEvidence=models['official-person-evidence'];sys.modules[base.__name__]=base
clock=types.ModuleType('backend.app.models.discovery');clock.now=lambda:datetime(2026,11,15,12,tzinfo=timezone.utc);sys.modules[clock.__name__]=clock
load(scope,'backend/app/services/people_discovery/normalizer.py',{'mark_ambiguities'})
async def main():
 out=[]
 for row in json.load(sys.stdin):
  try:
   if row['op']=='unique':
    unique={}
    for p in row['people']:
     p=models['public-person'].model_validate(p);unique.setdefault(p.linkedin_url,p)
    value=[p.model_dump(mode='json') for p in scope['mark_ambiguities'](list(unique.values()))]
   else:
    query=models['people-query'].model_validate(row['query']);captured=[]
    async def results(text,limit):captured.append(text);return row['records'][:limit] if isinstance(row['records'],list) else row['records']
    adapter=scope['PublicSearchAdapter']('fictional_unused');adapter.results=results
    people,errors=await (adapter.search_official(query) if row['op']=='official' else adapter.search(query))
    value={'query':captured[0],'result':{'people':[p.model_dump(mode='json') for p in people],'errors':['public_search_record_invalid']*len(errors)}}
   out.append({'ok':True,'value':value})
  except (ValueError,TypeError,AttributeError,KeyError):out.append({'ok':False})
 assert 'backend.app.core.config' not in sys.modules;assert 'httpx' not in sys.modules
 print(json.dumps(out))
asyncio.run(main())
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
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
#[test]
fn search_index_candidates_and_queries_match_actual_roles_names_urls_and_company_attribution() {
    let mut cases = Vec::new();
    for (role, text) in [
        ("founder", "Founder"),
        ("founder", "Co-founder"),
        ("co-founder", "Cofounder"),
        ("ceo", "Chief Executive Officer"),
        ("cto", "Chief Technology Officer"),
        ("head of engineering", "Head of Engineering"),
        ("vp engineering", "VP of Engineering"),
        ("engineering manager", "Engineering Manager"),
        ("technical recruiter", "Technical Recruiter"),
        ("software engineer", "Software Engineer"),
        ("software developer", "Software Developer"),
        ("technical staff", "Platform Engineer"),
        ("talent acquisition", "Talent Acquisition"),
        ("recruiter", "Recruiting"),
    ] {
        cases.push(json!({"op":"public","query":{"company_name":"Fictional Company","roles":[role]},"records":[{"title":format!("Fictional Professional | {text} at Fictional Company"),"link":"https://linkedin.com/in/fictional-professional?utm_source=fixture","snippet":"PRIVATE_SNIPPET_CANARY"}]}));
    }
    for n in 0..26 {
        let mut q = json!({"company_name":"Fictional Company"});
        let mut row = json!({"title":"Fictional Professional | CTO at Fictional Company","link":"https://linkedin.com/in/fictional-professional","snippet":"PRIVATE_SNIPPET_CANARY"});
        match n {
            0 => {}
            1 => row["title"] = json!("Fictional Professional — CTO at Fictional Company"),
            2 => row["title"] = json!("Fictional Professional – CTO at Fictional Company"),
            3 => row["title"] = json!("Fictional Professional - CTO at Fictional Company"),
            4 => row["title"] = json!("Fictional Professional|CTO at Fictional Company"),
            5 => {
                row["title"] =
                    json!("Fictional Professional\u{001c}|\u{001f}CTO at Fictional Company")
            }
            6 => row["title"] = json!("Fictional Professional | PreCTO at Fictional Company"),
            7 => row["title"] = json!("Fictional Professional | CTO2 at Fictional Company"),
            8 => row["title"] = json!("Fictional Professional | CTO at Other Company"),
            9 => row["title"] = json!("Fictional Professional | Engineer at Fictional Company"),
            10 => row["link"] = json!("https://company-fixture.example/team"),
            11 => row["link"] = json!("https://linkedin.com/company/fictional"),
            12 => row["link"] = json!("https://127.0.0.1/private"),
            13 => {
                row.as_object_mut().unwrap().remove("link");
            }
            14 => row["title"] = Value::Null,
            15 => row["snippet"] = Value::Null,
            16 => row["title"] = json!(format!("{} | CTO at Fictional Company", "a".repeat(101))),
            17 => row["title"] = json!(" | CTO at Fictional Company"),
            18 => {
                q["company_domain"] = json!("fictional-fixture.example");
                q["location"] = json!("India");
            }
            19 => q["roles"] = json!(["recruiter", "cto"]),
            20 => row = json!("malformed"),
            21 => row["title"] = json!(1),
            22 => {
                q["roles"] = json!(["software engineer"]);
                row["title"] =
                    json!("Fictional Professional | Software Engıneer at Fictional Company");
            }
            23 => {
                q["company_name"] = json!("Straße Company");
                row["title"] = json!("Fictional Professional | CTO at STRASSE Company");
            }
            24 => row["title"] = json!("Fictional Professional | CTOé at Fictional Company"),
            _ => {
                row["title"] = json!("Fictional Professional | CTO\u{0301} at Fictional Company");
                q["limit"] = json!(1);
            }
        }
        cases.push(json!({"op":"public","query":q,"records":[row]}));
    }
    for n in 0..20 {
        let mut q = json!({"company_name":"Fictional Company","company_domain":"company-fixture.example","research_mode":"official_company"});
        let mut row = json!({"title":"Fictional Professional | CTO at Fictional Company","link":"https://company-fixture.example/team","snippet":"PRIVATE_OFFICIAL_SNIPPET_CANARY"});
        match n {
            0 => {}
            1 => row["link"] = json!("https://www.company-fixture.example/team"),
            2 => row["link"] = json!("https://sub.company-fixture.example/team"),
            3 => row["link"] = json!("https://company-fixture.example.evil.example/team"),
            4 => row["title"] = json!("One | CTO at Fictional Company"),
            5 => row["title"] = json!("One Two Three Four Five Six | CTO at Fictional Company"),
            6 => row["title"] = json!("One Two Three Four Five | CTO at Fictional Company"),
            7 => row["title"] = json!("Fictional Professional CTO at Fictional Company"),
            8 => {
                row["title"] =
                    json!("Fictional Professional | Chief Technology Officer at Fictional Company")
            }
            9 => row["title"] = json!("Fictional Professional | CTO at Other Company"),
            10 => row["title"] = json!("Fictional Professional | CTO2 at Fictional Company"),
            11 => row["title"] = json!("Fictional Professional — CTO at Fictional Company"),
            12 => row["title"] = json!("Fictional Professional – CTO at Fictional Company"),
            13 => {
                row["title"] =
                    json!("Fictional Professional\u{001c}|\u{001f}CTO at Fictional Company")
            }
            14 => {
                q["roles"] = json!(["software engineer"]);
                row["title"] =
                    json!("Fictional Professional | Software Engıneer at Fictional Company");
            }
            15 => row["snippet"] = Value::Null,
            16 => row = Value::Null,
            17 => row["link"] = json!("https://127.0.0.1/team"),
            18 => {
                row["link"] = json!("https://company-fixture.example/team?utm_source=fixture");
                q["location"] = json!("India");
            }
            _ => q["roles"] = json!(["recruiter", "cto"]),
        }
        cases.push(json!({"op":"official","query":q,"records":[row]}));
    }
    let actual = oracle(json!(cases));
    for (i, (c, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let parsed = if c["op"] == "official" {
            rules::official_people(
                &c["records"],
                &c["query"],
                now(),
                "https://serper.dev/terms",
            )
        } else {
            rules::public_profiles(&c["records"], &c["query"], now())
        };
        let got = match parsed
            .and_then(|v| Ok(json!({"query":rules::query(&c["query"],now())?,"result":v})))
        {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "search candidate {i}");
        for canary in ["PRIVATE_SNIPPET_CANARY", "PRIVATE_OFFICIAL_SNIPPET_CANARY"] {
            assert!(!got.to_string().contains(canary));
        }
        for person in got["value"]["result"]["people"]
            .as_array()
            .into_iter()
            .flatten()
        {
            assert_ne!(person["human_confirmed"], true);
            assert!(person.get("business_email").is_none_or(Value::is_null));
        }
    }
}
#[test]
fn canonical_url_deduplication_precedes_actual_unicode_name_ambiguity_and_parser_bounds() {
    let person = json!({"name":"Fictional Professional","role":"cto","linkedin_url":"https://linkedin.com/in/fictional-first","evidence_url":"https://company-fixture.example/team","verification_status":"source_reported"});
    let mut cases = Vec::new();
    for n in 0..8 {
        let a = person.clone();
        let mut b = person.clone();
        b["linkedin_url"] = json!("https://linkedin.com/in/fictional-second");
        match n {
            0 => {}
            1 => b["name"] = json!("FICTIONAL PROFESSIONAL"),
            2 => b["name"] = json!("Different Professional"),
            3 => b["name"] = Value::Null,
            4 => {
                b["linkedin_url"] =
                    json!("https://www.linkedin.com/in/fictional-first/?utm_source=fixture")
            }
            5 => b["name"] = json!("Fictional Professional "),
            6 => b["name"] = json!(""),
            _ => b["linkedin_url"] = json!("https://linkedin.com/in/fictional-first"),
        }
        cases.push(json!({"op":"unique","people":[a,b]}));
    }
    let actual = oracle(json!(cases));
    for (i, (c, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = rules::unique_people(c["people"].as_array().unwrap().clone(), now()).unwrap();
        assert_eq!(json!({"ok":true,"value":got}), *want, "ambiguity {i}");
    }
    let q = json!({"company_name":"Fictional Company"});
    assert!(rules::public_profiles(&json!({}), &q, now()).is_err());
    assert!(rules::public_profiles(&json!([{"snippet":"x".repeat(1048576)}]), &q, now()).is_err());
    assert!(rules::unique_people(vec![person; 21], now()).is_err());
    assert!(!rules::official_url(
        &json!("https://company-fixture.example@other.example/team"),
        "company-fixture.example"
    ));
}
