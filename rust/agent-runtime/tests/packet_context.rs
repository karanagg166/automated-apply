use automated_apply_agents::packet_context;
use serde_json::Value;
#[test]
fn packet_material_fingerprints_and_snapshots_match_the_original_recipe() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-context-corpus.json")).unwrap();
    let now = chrono::DateTime::parse_from_rfc3339(corpus["now"].as_str().unwrap())
        .unwrap()
        .with_timezone(&chrono::Utc);
    let mut failures = vec![];
    for (i, raw) in corpus["records"].as_array().unwrap().iter().enumerate() {
        let actual = packet_context::build(raw.clone(), &Default::default(), now)
            .map(|built| built.snapshot);
        if !actual.as_ref().is_ok_and(|v| v == &corpus["outputs"][i]) {
            failures.push(format!(
                "{i}: actual{actual:?} expected{}",
                corpus["outputs"][i]
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(4).collect::<Vec<_>>().join("\n")
    );
}
