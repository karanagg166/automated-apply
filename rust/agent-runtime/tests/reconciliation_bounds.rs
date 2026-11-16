use automated_apply_agents::execution::read_bounds;
use serde_json::json;
#[test]
fn lost_reconciliation_lease_and_read_admission_responses_have_independent_durable_ceilings() {
    for operation in ["verify_account", "reconcile_application"] {
        let mut lost_poll = json!({"operation":operation});
        for _ in 0..3 {
            assert!(read_bounds::claim(&mut lost_poll).unwrap());
        }
        assert!(read_bounds::exhausted(&lost_poll).unwrap());
        assert!(!read_bounds::claim(&mut lost_poll).unwrap());
        let before = lost_poll.clone();
        assert!(!read_bounds::claim(&mut lost_poll).unwrap());
        assert_eq!(lost_poll, before);
        let mut one_lease = json!({"operation":operation});
        assert!(read_bounds::claim(&mut one_lease).unwrap());
        for _ in 0..3 {
            read_bounds::admit(&mut one_lease).unwrap();
        }
        assert!(read_bounds::exhausted(&one_lease).unwrap());
        assert_eq!(
            read_bounds::admit(&mut one_lease).unwrap_err().0,
            "bounded_reconciliation_exhausted"
        );
    }
}
#[test]
fn legacy_reported_exhaustion_and_corrupt_counters_never_reset_or_authorize_a_read() {
    let mut old = json!({"operation":"reconcile_application","account_recheck_attempts":3});
    assert!(!read_bounds::claim(&mut old).unwrap());
    let before = old.clone();
    assert!(!read_bounds::claim(&mut old).unwrap());
    assert_eq!(old, before);
    for value in [json!(-1), json!("lost"), json!(null), json!(true)] {
        let mut work = json!({"operation":"reconcile_application","reconciliation_attempts":value});
        assert!(read_bounds::exhausted(&work).is_err());
        assert!(read_bounds::claim(&mut work).is_err());
        assert!(read_bounds::admit(&mut work).is_err());
    }
    let mut discovery = json!({"operation":"inspect_job"});
    read_bounds::admit(&mut discovery).unwrap();
    assert!(read_bounds::claim(&mut discovery).unwrap());
    assert_eq!(discovery, json!({"operation":"inspect_job"}));
}
