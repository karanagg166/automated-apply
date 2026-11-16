//! Deferred actual startup query DTO and explicit filter comparisons. No settings/providers.
use automated_apply_agents::startup_catalog::{
    contract::{self, Kind},
    rules,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(script: &str, input: Value) -> Value {
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
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
#[test]
fn startup_actual_filter_and_shortlist_dtos_preserve_defaults_coercions_optional_values_and_constraints()
 {
    let mut cases: Vec<(Kind, &str, Value)> = Vec::new();
    for n in 0..56 {
        let mut v = json!({});
        match n {
            0 => {}
            1 => v["max_employees"] = Value::Null,
            2 => {
                v["min_employees"] = json!(51);
                v["max_employees"] = json!(50);
            }
            3 => {
                v["min_employees"] = json!("11");
                v["max_employees"] = json!("100");
            }
            4 => v["max_employees"] = json!(true),
            5 => v["max_employees"] = json!(1.5),
            6 => v["min_employees"] = json!(0),
            7 => v["max_employees"] = json!(10000001),
            8 => v["country"] = json!("  India  "),
            9 => v["country"] = json!("   "),
            10 => v["query"] = json!("  untouched query  "),
            11 => v["query"] = json!(""),
            12 => v["source"] = json!(" manual "),
            13 => v["yc_batch"] = json!(" W26 "),
            14 => v["industries"] = json!([" AI ", " SaaS "]),
            15 => v["industries"] = json!([""]),
            16 => v["industries"] = json!([1]),
            17 => v["industries"] = json!(vec!["AI"; 21]),
            18 => v["size_bands"] = json!(["2-10", "11-50"]),
            19 => v["size_bands"] = json!([" 1-10 "]),
            20 => v["size_bands"] = json!(["100-200"]),
            21 => v["size_bands"] = json!(vec!["unknown"; 7]),
            22 => v["roles"] = json!([" CTO ", " Recruiter "]),
            23 => v["skills"] = json!(vec!["Rust"; 31]),
            24 => v["locations"] = json!(vec!["India"; 11]),
            25 => v["stages"] = json!(vec!["seed"; 11]),
            26 => v["use_profile"] = json!("YES"),
            27 => v["include_unknown_size"] = json!(0),
            28 => v["early_stage"] = json!(2),
            29 => v["early_stage"] = Value::Null,
            30 => v["exact_employee_count"] = json!(true),
            31 => v["has_business_email"] = json!("off"),
            32 => v["has_technical_staff"] = json!(1),
            33 => v["verified_yc"] = json!(false),
            34 => v["has_leader_evidence"] = json!("true"),
            35 => v["minimum_score"] = json!("50.5"),
            36 => v["minimum_score"] = json!(true),
            37 => v["minimum_score"] = json!(101),
            38 => v["minimum_score"] = json!(-1),
            39 => v["minimum_score"] = json!("NaN"),
            40 => v["freshness_days"] = json!("365"),
            41 => v["freshness_days"] = json!(366),
            42 => v["page"] = json!(0),
            43 => v["page"] = json!(250),
            44 => v["page"] = json!(251),
            45 => v["limit"] = json!("100"),
            46 => v["limit"] = json!(101),
            47 => v["observed_after"] = json!("2026-11-16T12:34:56Z"),
            48 => v["observed_after"] = json!("2026-11-16T12:34:56.123456789+05:30"),
            49 => v["observed_after"] = json!("2026-11-16T12:34:56"),
            50 => v["observed_after"] = json!(1794832496),
            51 => v["remote_preference"] = json!("remote"),
            52 => v["remote_preference"] = json!(" remote "),
            53 => v["application_status"] = json!("packet_prepared"),
            54 => v["extra"] = json!(true),
            _ => v = Value::Null,
        }
        cases.push((Kind::Filters, "startup-filters", v));
    }
    for v in [
        json!({}),
        json!({"note":"  Preserve explicit note spacing  "}),
        json!({"note":null}),
        json!({"note":5}),
        json!({"note":"x".repeat(2001)}),
        json!({"run_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"}),
        json!({"run_id":null}),
        json!({"run_id":"wrong"}),
        json!({"run_id":1}),
        json!({"extra":true}),
        Value::Null,
        json!([]),
    ] {
        cases.push((Kind::Shortlist, "startup-shortlist", v));
    }
    let actual = oracle(
        r#"import json,runpy,sys
m=runpy.run_path('rust/scripts/export_startup_contracts.py')['models']();out=[]
for row in json.load(sys.stdin):
 try:out.append({'ok':True,'value':m[row['name']].model_validate(row['value']).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules;print(json.dumps(out))
"#,
        json!(
            cases
                .iter()
                .map(|(_, name, value)| json!({"name":name,"value":value}))
                .collect::<Vec<_>>()
        ),
    );
    for (index, ((kind, _, input), want)) in cases
        .into_iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        let got = match contract::normalize(kind, input) {
            Ok(value) => json!({"ok":true,"value":value}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "case {index}");
    }
}
#[test]
fn startup_size_role_location_and_industry_filters_match_actual_source_without_inferred_headcounts()
{
    let mut cases = Vec::new();
    let mut native = Vec::new();
    for (count, name) in [
        (None, "unknown"),
        (None, "1-10"),
        (None, "2-10"),
        (None, "11-50"),
        (None, "51-200"),
        (None, "201-500"),
        (None, "500+"),
        (Some(9), "1-10"),
    ] {
        for filter in [
            json!({}),
            json!({"max_employees":null}),
            json!({"min_employees":11,"max_employees":null}),
            json!({"exact_employee_count":true}),
            json!({"include_unknown_size":false}),
            json!({"max_employees":10}),
            json!({"size_bands":["2-10"]}),
            json!({"min_employees":2,"max_employees":10}),
        ] {
            let filter = contract::normalize(Kind::Filters, filter).unwrap();
            let size = json!({"employee_count":count,"team_size_band":name});
            cases.push(json!({"op":"size_allowed","size":size,"filters":filter}));
            native.push(json!(rules::size_allowed(&size, &filter).unwrap()));
        }
    }
    for count in [
        None,
        Some(1),
        Some(2),
        Some(10),
        Some(11),
        Some(50),
        Some(51),
        Some(200),
        Some(201),
        Some(500),
        Some(501),
        Some(10000000),
    ] {
        cases.push(json!({"op":"size_band","count":count}));
        native.push(json!(rules::size_band(count).unwrap()));
    }
    for (title, roles) in [
        ("CTO", vec!["cto"]),
        ("Engineer", vec!["Recruiter"]),
        ("Technical Recruiter", vec!["recruiter"]),
        ("Straße Engineer", vec!["STRASSE"]),
        ("", vec![]),
        ("Rust Developer", vec!["developer", "CTO"]),
    ] {
        let roles = roles.into_iter().map(String::from).collect::<Vec<_>>();
        cases.push(json!({"op":"role_allowed","title":title,"roles":roles}));
        native.push(json!(rules::role_allowed(title, &roles)));
    }
    for (industry, requested) in [
        (Some("Retail"), vec!["AI"]),
        (Some("AI research"), vec!["AI"]),
        (Some("Artificial intelligence"), vec!["AI"]),
        (Some("B2B Software as a Service"), vec!["SaaS"]),
        (Some("Financial technology"), vec!["fintech"]),
        (Some("Developer tooling"), vec!["developer tools"]),
        (Some("DevTools"), vec!["developer tools"]),
        (Some("ai_tools"), vec!["AI"]),
        (Some("ai-tools"), vec!["AI"]),
        (Some("retail AI"), vec!["AI"]),
        (Some("fintechs"), vec!["fintech"]),
        (Some("SaaS2"), vec!["SaaS"]),
        (None, vec![]),
        (None, vec!["AI"]),
        (Some("Straße"), vec!["STRASSE"]),
        (Some("医療AI"), vec!["AI"]),
    ] {
        let requested = requested.into_iter().map(String::from).collect::<Vec<_>>();
        cases.push(json!({"op":"industry_allowed","industry":industry,"requested":requested}));
        native.push(json!(rules::industry_allowed(industry, &requested)));
    }
    for filter in [
        json!({}),
        json!({"locations":["Bengaluru"],"remote_preference":"remote"}),
        json!({"locations":["Delhi"],"remote_preference":"any"}),
        json!({"locations":["Bengaluru"],"remote_preference":"hybrid"}),
        json!({"remote_preference":"onsite"}),
        json!({"remote_preference":null}),
    ] {
        for remote in ["remote", "hybrid"] {
            let filter = contract::normalize(Kind::Filters, filter.clone()).unwrap();
            let locations = vec!["Bengaluru, India".to_owned()];
            let remotes = vec![remote.to_owned()];
            cases.push(json!({"op":"location_allowed","locations":locations,"remotes":remotes,"filters":filter}));
            native.push(json!(
                rules::location_allowed(&locations, &remotes, &filter).unwrap()
            ));
        }
    }
    let actual = oracle(
        r#"import json,re,runpy,sys
from datetime import timezone
from types import SimpleNamespace as NS
s={'__name__':'startup_rule_fixture','re':re,'timezone':timezone};runpy.run_path('rust/scripts/export_execution_contracts.py')['load'](s,'backend/app/services/startup_discovery/normalizer.py',{'BANDS','utc','size_band','size_allowed','role_allowed','location_allowed','industry_allowed'})
out=[]
for row in json.load(sys.stdin):
 op=row.pop('op');args={k:NS(**v) if k=='filters' else v for k,v in row.items()};out.append(s[op](**args))
assert 'backend.app.core.config' not in sys.modules;print(json.dumps(out))
"#,
        json!(cases),
    );
    assert_eq!(json!(native), actual);
    assert!(rules::size_band(Some(0)).is_err());
}
#[test]
fn startup_get_filters_keep_repeated_lists_but_refuse_duplicate_scalars_or_unbounded_queries() {
    let value=contract::query(Some("industries=AI&industries=SaaS&roles=CTO&roles=Recruiter&max_employees=100&early_stage=false")).unwrap();
    assert_eq!(value["industries"], json!(["AI", "SaaS"]));
    assert_eq!(value["roles"], json!(["CTO", "Recruiter"]));
    assert_eq!(value["max_employees"], 100);
    assert_eq!(value["early_stage"], false);
    for query in [
        "page=1&page=2",
        "unknown=true",
        "min_employees=100&max_employees=50",
        "remote_preference=wrong",
        "limit=101",
    ] {
        assert!(contract::query(Some(query)).is_err(), "{query}");
    }
    assert!(contract::query(Some(&"x".repeat(16385))).is_err());
}
