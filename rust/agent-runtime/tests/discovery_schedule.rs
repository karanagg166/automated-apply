use automated_apply_agents::discovery_schedule;
use serde_json::json;
#[test]
fn schedule_updates_are_revision_bound_closed_and_only_select_fixed_public_feeds() {
    assert!(discovery_schedule::request(br#"{"expected_revision":0,"enabled":[]}"#).is_ok());
    assert!(
        discovery_schedule::request(
            br#"{"expected_revision":0,"enabled":["himalayas","we_work_remotely"]}"#
        )
        .is_ok()
    );
    for raw in [
        json!({"expected_revision":-1,"enabled":[]}),
        json!({"expected_revision":0,"enabled":["himalayas","himalayas"]}),
        json!({"expected_revision":0,"enabled":["naukri"]}),
        json!({"expected_revision":0,"enabled":[],"apply":true}),
        json!({"expected_revision":0,"enabled":[],"url":"https://evil.example"}),
    ] {
        assert!(discovery_schedule::request(raw.to_string().as_bytes()).is_err());
    }
}
