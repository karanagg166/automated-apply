use automated_apply_agents::{packet_contract, packet_fields, resources};
use serde_json::{Value, json};
#[test]
fn packet_fields_match_actual_legacy_mapping_with_explicit_narrative_and_upload_boundaries() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-fields-corpus.json")).unwrap();
    let job = corpus["job_id"].as_str().unwrap().parse().unwrap();
    let inventories = corpus["resources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| serde_json::from_value::<Vec<resources::Resource>>(v.clone()).unwrap())
        .collect::<Vec<_>>();
    let resumes = inventories
        .iter()
        .map(|r| resources::select_resume(r, None).unwrap())
        .collect::<Vec<_>>();
    let mut failures = vec![];
    for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let index = |n: usize| case[n].as_u64().unwrap() as usize;
        let profile =
            (!corpus["profiles"][index(0)].is_null()).then_some(&corpus["profiles"][index(0)]);
        let question = packet_contract::question(corpus["questions"][index(2)].clone()).unwrap();
        let prepared = packet_fields::prepare(
            question,
            job,
            profile,
            Some(&resumes[index(1)]),
            if index(2) < 7 {
                "packet_core"
            } else {
                "user_provided"
            },
        )
        .unwrap();
        let resolution = json!(prepared.resolution);
        let result = if prepared.resolution.is_some() {
            packet_fields::resolved(prepared, &corpus["answers"][index(3)], profile.unwrap())
        } else {
            Ok(prepared.field)
        };
        let expected = &corpus["outputs"][index(4)];
        let actual = result.map(|mut v| {
            v.as_object_mut().unwrap().remove("id");
            v
        });
        if actual.is_ok() != (expected["accepted"] == true)
            || actual.as_ref().is_ok_and(|v| v != &expected["field"])
            || resolution != expected["resolution"]
        {
            failures.push(format!(
                "{i}: {case} actual{actual:?} resolution{resolution} expected{expected}"
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
