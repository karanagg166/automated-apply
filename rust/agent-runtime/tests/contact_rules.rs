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
