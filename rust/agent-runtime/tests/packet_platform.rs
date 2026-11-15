use automated_apply_agents::packet_platform::{self, Policy};
use serde_json::{Value, json};
#[test]
fn packet_destinations_match_actual_adapter_rules_without_network_or_action_authority() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-platform-corpus.json")).unwrap();
    assert_eq!(packet_platform::capabilities(), corpus["capabilities"]);
    let now = corpus["now"].as_str().unwrap().parse().unwrap();
    let observations = corpus["observations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| serde_json::from_value::<Vec<(String, String)>>(v.clone()).unwrap())
        .collect::<Vec<_>>();
    let mut failures = vec![];
    for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let index = |n: usize| case[n].as_u64().unwrap() as usize;
        let raw = &corpus["policies"][index(2)];
        let policy = Policy {
            testing: raw["testing"].as_bool().unwrap(),
            origins: serde_json::from_value(raw["origins"].clone()).unwrap(),
        };
        let actual = packet_platform::select(
            &corpus["jobs"][index(0)],
            &observations[index(1)],
            &policy,
            now,
        )
        .map(|v| json!(v));
        if !actual
            .as_ref()
            .is_ok_and(|v| v == &corpus["results"][index(3)])
        {
            failures.push(format!(
                "{i}: {case} actual{actual:?} expected{}",
                corpus["results"][index(3)]
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}
