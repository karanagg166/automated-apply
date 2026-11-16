//! Deferred actual company/startup/professional research validation. Fictional inputs only.
use automated_apply_agents::research_contract::{self, Kind};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn company() -> Value {
    json!({"name":"Fictional Company","source":"manual","source_url":"https://company-fixture.example/about","permission_evidence_url":"https://company-fixture.example/terms","observed_at":"2026-11-15T12:00:00Z"})
}
fn official() -> Value {
    json!({"full_name":"Fictional Professional","role_title":"CTO","evidence_url":"https://company-fixture.example/team","permission_evidence_url":"https://company-fixture.example/terms","observed_at":"2026-11-15T12:00:00Z"})
}
#[test]
fn research_inputs_match_actual_company_people_and_startup_defaults_urls_timestamps_counts_and_permission_rules()
 {
    let mut cases: Vec<(Kind, &str, Value)> = Vec::new();
    for n in 0..36 {
        let mut v = json!({"linkedin_url":"https://linkedin.com/in/fictional-professional?utm_source=fixture","evidence_url":"https://company-fixture.example/team?utm_source=fixture"});
        match n {
            0 => {}
            1 => v["name"] = json!("  Preserved name spacing  "),
            2 => v["role"] = json!(" CTO "),
            3 => v["name"] = json!(""),
            4 => v["name"] = json!(1),
            5 => v["name"] = json!("x".repeat(256)),
            6 => v["role"] = json!("x".repeat(256)),
            7 => v["source"] = json!("public_search"),
            8 => v["source"] = json!("apollo"),
            9 => v["verification_status"] = json!("source_reported"),
            10 => v["verification_status"] = json!("human_confirmed"),
            11 => v["outreach_mode"] = json!("automatic"),
            12 => v["evidence_text"] = json!("x".repeat(4001)),
            13 => v["evidence_text"] = json!("  preserved snippet  "),
            14 => v["linkedin_url"] = json!("https://linkedin.com/company/fictional"),
            15 => v["linkedin_url"] = json!("https://example.com/in/fictional"),
            16 => v["linkedin_url"] = json!("http://linkedin.com/in/fictional"),
            17 => v["linkedin_url"] = json!("https://www.linkedin.com/in/fictional/"),
            18 => v["linkedin_url"] = json!("https://in.linkedin.com/in/fictional"),
            19 => v["linkedin_url"] = json!("https://linkedin.com/in/fictional/extra"),
            20 => v["linkedin_url"] = json!("https://linkedin.com/in/fictional%20person"),
            21 => v["linkedin_url"] = json!("https://linkedin.com/in/Fictional_123-Name"),
            22 => v["linkedin_url"] = json!(""),
            23 => v["linkedin_url"] = Value::Null,
            24 => v["evidence_url"] = json!("https://127.0.0.1/private"),
            25 => v["evidence_url"] = json!("https://user:secret@company-fixture.example/team"),
            26 => v["evidence_url"] = json!("javascript:alert(1)"),
            27 => {
                v["evidence_url"] =
                    json!("https://company-fixture.example/team?b=2&a=1&ref=fixture#section")
            }
            28 => v["evidence_url"] = json!("https://boards.greenhouse.io/fictional/jobs/123456"),
            29 => v["unexpected_private_payload"] = json!(true),
            30 => {
                v.as_object_mut().unwrap().remove("linkedin_url");
            }
            31 => {
                v.as_object_mut().unwrap().remove("evidence_url");
            }
            32 => v = Value::Null,
            33 => v["role"] = Value::Null,
            34 => v["evidence_text"] = Value::Null,
            _ => v = json!([]),
        }
        cases.push((Kind::PublicPerson, "public-person", v));
    }
    for n in 0..36 {
        let mut v = official();
        match n {
            0 => {}
            1 => v["full_name"] = json!("  Fictional Professional  "),
            2 => v["role_title"] = json!(" CTO "),
            3 => v["full_name"] = json!(" "),
            4 => v["role_title"] = json!(""),
            5 => v["full_name"] = json!("x".repeat(201)),
            6 => v["evidence_url"] = json!("https://127.0.0.1/private"),
            7 => v["permission_evidence_url"] = json!("http://company-fixture.example/terms"),
            8 => v["professional_url"] = json!("https://github.com/fictional-person"),
            9 => v["professional_url"] = json!("private-file:one"),
            10 => v["observed_at"] = json!("2026-11-15T12:00:00"),
            11 => v["observed_at"] = json!("2026-11-15T17:30:00+05:30"),
            12 => v["observed_at"] = json!("2026-11-15T12:00:00.123456789Z"),
            13 => v["observed_at"] = json!(1794744000),
            14 => v["observed_at"] = json!("2099-01-01T00:00:00Z"),
            15 => v["observed_at"] = json!("invalid"),
            16 => v["observed_at"] = Value::Null,
            17 => v["human_confirmed"] = json!("YES"),
            18 => v["human_confirmed"] = json!(0),
            19 => v["human_confirmed"] = json!(2),
            20 => {
                v["business_email"] = json!("Person@EXAMPLE.COM");
                v["email_publication_url"] = json!("https://company-fixture.example/contact");
            }
            21 => v["business_email"] = json!("person@example.com"),
            22 => v["email_publication_url"] = json!("https://company-fixture.example/contact"),
            23 => {
                v["business_email"] = json!("bad");
                v["email_publication_url"] = json!("https://company-fixture.example/contact");
            }
            24 => {
                v["business_email"] = json!("person@example.com");
                v["email_publication_url"] = json!("https://localhost/contact");
            }
            25 => {
                v["business_email"] = Value::Null;
                v["email_publication_url"] = Value::Null;
            }
            26 => v["business_email"] = json!(""),
            27 => v["email_publication_url"] = json!(""),
            28 => v["extra"] = json!(true),
            29 => v["full_name"] = json!(1),
            30 => v["human_confirmed"] = Value::Null,
            31 => {
                v.as_object_mut().unwrap().remove("evidence_url");
            }
            32 => {
                v.as_object_mut().unwrap().remove("observed_at");
            }
            33 => v = Value::Null,
            34 => v["role_title"] = json!("\u{001c}CTO\u{001f}"),
            _ => v = json!([]),
        }
        cases.push((Kind::OfficialPerson, "official-person-evidence", v));
    }
    for n in 0..32 {
        let mut v = json!({"company_name":"Fictional Company"});
        match n {
            0 => {}
            1 => v["company_name"] = json!("  Fictional Company  "),
            2 => v["company_name"] = json!(" "),
            3 => v["company_domain"] = json!("  COMPANY-FIXTURE.EXAMPLE. "),
            4 => v["company_domain"] = json!("https://company-fixture.example"),
            5 => v["company_domain"] = json!("localhost"),
            6 => v["company_domain"] = json!("127.0.0.1"),
            7 => v["company_domain"] = Value::Null,
            8 => v["roles"] = json!(["cto", "recruiter"]),
            9 => v["roles"] = json!([]),
            10 => v["roles"] = json!(["CTO"]),
            11 => v["roles"] = json!(vec!["cto"; 11]),
            12 => v["location"] = json!("  India  "),
            13 => v["location"] = json!(" "),
            14 => v["limit"] = json!("20"),
            15 => v["limit"] = json!(21),
            16 => v["limit"] = json!(true),
            17 => v["source"] = json!("linkedin"),
            18 => v["source"] = json!("manual"),
            19 => v["source"] = json!("apollo"),
            20 => v["allow_paid"] = json!("true"),
            21 => v["allow_paid"] = json!(2),
            22 => v["permission_confirmed"] = json!("YES"),
            23 => v["research_mode"] = json!("official_company"),
            24 => v["research_mode"] = json!("wrong"),
            25 => {
                v["manual_people"] = json!([{"linkedin_url":"https://linkedin.com/in/fictional","evidence_url":"https://company-fixture.example/team"}])
            }
            26 => v["official_people"] = json!([official()]),
            27 => v["official_people"] = json!(vec![official(); 21]),
            28 => v["manual_people"] = Value::Null,
            29 => v["extra"] = json!(true),
            30 => v = Value::Null,
            _ => v["company_name"] = json!("x".repeat(201)),
        }
        cases.push((Kind::PeopleQuery, "people-query", v));
    }
    for n in 0..36 {
        let mut v = company();
        match n {
            0 => {}
            1 => v["name"] = json!(" Fictional Company "),
            2 => v["source"] = json!(" Manual "),
            3 => v["source"] = json!("a"),
            4 => v["domain"] = json!(" COMPANY-FIXTURE.EXAMPLE. "),
            5 => v["domain"] = json!("https://company-fixture.example"),
            6 => v["country"] = json!(" India "),
            7 => v["technology_stack"] = json!([" Rust ", " Python "]),
            8 => v["technology_stack"] = json!(vec!["Rust"; 31]),
            9 => v["observed_at"] = json!("2026-11-15T12:00:00"),
            10 => v["observed_at"] = json!("2026-11-15T17:30:00+05:30"),
            11 => v["employee_count"] = json!(12),
            12 => v["employee_count"] = json!(12.0),
            13 => v["employee_count"] = json!("12"),
            14 => v["employee_count"] = json!(true),
            15 => v["employee_count"] = json!(0),
            16 => v["employee_count"] = json!(10000001),
            17 => {
                v["employee_count"] = json!(2);
                v["team_size_band"] = json!("2-10");
            }
            18 => {
                v["employee_count"] = json!(1);
                v["team_size_band"] = json!("2-10");
            }
            19 => {
                v["employee_count"] = json!(12);
                v["team_size_band"] = json!("1-10");
            }
            20 => v["team_size_band"] = json!("11-50"),
            21 => v["historical"] = json!("true"),
            22 => v["hiring_statement"] = json!("not_currently_hiring"),
            23 => {
                v["hiring_statement"] = json!("not_currently_hiring");
                v["authoritative_statement"] = json!(true);
            }
            24 => v["hiring_statement"] = json!("hiring_possible"),
            25 => v["founding_year"] = json!("2020"),
            26 => v["founding_year"] = json!(1799),
            27 => v["description"] = json!("x".repeat(4001)),
            28 => v["careers_url"] = json!("https://company-fixture.example/jobs"),
            29 => v["source_url"] = json!("https://127.0.0.1/private"),
            30 => v["verification_status"] = json!("human_confirmed"),
            31 => v["verification_status"] = json!("verified"),
            32 => v["extra"] = json!(true),
            33 => v = Value::Null,
            34 => v["observed_at"] = json!("2099-01-01T00:00:00Z"),
            _ => v["source_company_id"] = json!("  original ID  "),
        }
        cases.push((Kind::CompanyObservation, "company-observation", v));
    }
    for n in 0..20 {
        let mut v = json!({"idempotency_key":"fictional_startup_request"});
        match n {
            0 => {}
            1 => v["idempotency_key"] = json!("short"),
            2 => v["mode"] = json!("job_led"),
            3 => v["source"] = json!("greenhouse"),
            4 => v["companies"] = json!([company()]),
            5 => {
                v["companies"] = json!([company()]);
                v["permission_confirmed"] = json!(true);
            }
            6 => {
                v["companies"] = json!([company()]);
                v["permission_confirmed"] = json!(true);
                v["mode"] = json!("job_led");
            }
            7 => {
                v["companies"] = json!([company()]);
                v["permission_confirmed"] = json!(true);
                v["source"] = json!("other");
            }
            8 => {
                v["companies"] = json!([company(), company()]);
                v["permission_confirmed"] = json!(true);
                v["query"] = json!({"limit":1});
            }
            9 => {
                v["query"] = json!({"keywords":[" Rust "],"locations":[" India "],"limit":"20","max_age_days":"14"})
            }
            10 => v["query"] = json!({"limit":101}),
            11 => v["query"] = Value::Null,
            12 => v["filters"] = json!({"max_employees":null,"early_stage":false}),
            13 => v["filters"] = json!({"min_employees":100,"max_employees":10}),
            14 => v["allow_paid"] = json!("YES"),
            15 => v["permission_confirmed"] = json!(2),
            16 => v["companies"] = json!(vec![company(); 101]),
            17 => v["extra"] = json!(true),
            18 => v = Value::Null,
            _ => {
                v["query"] = json!({"employment_types":["internship"],"remote_preference":"remote"})
            }
        }
        cases.push((Kind::StartupRun, "startup-run-request", v));
    }
    let script = r#"import json,runpy,sys
models=runpy.run_path('rust/scripts/export_people_contracts.py')['models']();models.update(runpy.run_path('rust/scripts/export_startup_contracts.py')['models']());out=[]
for row in json.load(sys.stdin):
 try:out.append({'ok':True,'value':models[row['name']].model_validate(row['value']).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules;print(json.dumps(out))
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
        .write_all(
            json!(
                cases
                    .iter()
                    .map(|(_, name, value)| json!({"name":name,"value":value}))
                    .collect::<Vec<_>>()
            )
            .to_string()
            .as_bytes(),
        )
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let actual: Value = serde_json::from_slice(&out.stdout).unwrap();
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc();
    for (index, ((kind, _, v), want)) in cases
        .into_iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        let got = match research_contract::normalize(kind, v, now) {
            Ok(value) => json!({"ok":true,"value":value}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
#[test]
fn research_contract_current_time_and_expanded_payload_bounds_are_explicit_and_grant_no_transport()
{
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc();
    let mut v = official();
    v["observed_at"] = json!("2026-11-17T00:05:00Z");
    assert!(research_contract::normalize(Kind::OfficialPerson, v.clone(), now).is_ok());
    v["observed_at"] = json!("2026-11-17T00:05:01Z");
    assert!(research_contract::normalize(Kind::OfficialPerson, v, now).is_err());
    let mut v = company();
    v["private"] = json!("x".repeat(2 * 1024 * 1024));
    assert!(research_contract::normalize(Kind::CompanyObservation, v, now).is_err());
    let input = research_contract::normalize(
        Kind::PeopleQuery,
        json!({"company_name":"Fictional","allow_paid":true}),
        now,
    )
    .unwrap();
    assert!(input.get("dispatch_authorized").is_none());
}
