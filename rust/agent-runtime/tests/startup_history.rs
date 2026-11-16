//! Deferred actual application-status semantics, including conservative multiple-packet evidence.
use automated_apply_agents::startup_catalog::search;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn startup_history_status_matches_actual_saved_job_and_packet_evidence_without_calling_preparation_applied()
 {
    let mut cases = Vec::new();
    let mut native = Vec::new();
    for status in ["discovered", "shortlisted", "applied", "rejected"] {
        for packet in [
            Value::Null,
            json!({"lifecycle_state":"created","tracking_state":"not_applied"}),
            json!({"lifecycle_state":"provider_confirmed_submitted","tracking_state":"not_applied"}),
            json!({"lifecycle_state":"user_reported_submitted","tracking_state":"interview_scheduled"}),
            json!({"lifecycle_state":"created","tracking_state":"application_rejected"}),
        ] {
            for filter in [
                "all",
                "not_applied",
                "applied",
                "packet_prepared",
                "shortlisted",
                "interview",
                "rejected",
            ] {
                let job = json!({"status":status});
                let packets = if packet.is_null() {
                    vec![]
                } else {
                    vec![packet.clone()]
                };
                native.push(json!(search::matches_status(&job, &packets, filter)));
                cases.push(json!({"job":job,"packet":packet,"filter":filter}));
            }
        }
    }
    let script = r#"import json,runpy,sys
from types import SimpleNamespace as NS
s={'__name__':'startup_status_fixture'};runpy.run_path('rust/scripts/export_execution_contracts.py')['load'](s,'backend/app/dashboard/states.py',{'SUBMITTED','matches_status'})
print(json.dumps([s['matches_status'](NS(**v['job']),NS(**v['packet']) if v['packet'] else None,v['filter']) for v in json.load(sys.stdin)]));assert 'backend.app.core.config' not in sys.modules
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
    assert_eq!(json!(native), actual);
    let job = json!({"status":"discovered"});
    let packets = [
        json!({"lifecycle_state":"provider_confirmed_submitted"}),
        json!({"lifecycle_state":"created"}),
    ];
    assert!(search::matches_status(&job, &packets, "applied"));
    assert!(!search::matches_status(&job, &packets, "not_applied"));
    assert!(!search::matches_status(&job, &packets, "packet_prepared"));
}
