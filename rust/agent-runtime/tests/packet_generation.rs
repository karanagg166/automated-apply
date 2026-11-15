use automated_apply_agents::{packet_contract, packet_fields, packet_generation, resources};
use serde_json::{Value, json};
#[test]
fn explicit_generation_mapping_requests_constraints_and_rewrite_match_actual_python_builder() {
    let data: Value =
        serde_json::from_str(include_str!("fixtures/packet-generation-corpus.json")).unwrap();
    let mut failures = vec![];
    for mode in data["modes"].as_array().unwrap() {
        let corpus = &mode["corpus"];
        let job = corpus["job_id"].as_str().unwrap().parse().unwrap();
        let resumes = corpus["resources"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| {
                resources::select_resume(
                    &serde_json::from_value::<Vec<resources::Resource>>(r.clone()).unwrap(),
                    None,
                )
                .unwrap()
            })
            .collect::<Vec<_>>();
        for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
            let index = |n: usize| case[n].as_u64().unwrap() as usize;
            let profile =
                (!corpus["profiles"][index(0)].is_null()).then_some(&corpus["profiles"][index(0)]);
            let prepared = packet_fields::prepare_generation(
                packet_contract::question(corpus["questions"][index(2)].clone()).unwrap(),
                job,
                profile,
                Some(&resumes[index(1)]),
                if index(2) < 7 {
                    "packet_core"
                } else {
                    "user_provided"
                },
                mode["rewrite"] == true,
            )
            .unwrap();
            let resolution = json!(prepared.resolution);
            let actual = if prepared.resolution.is_some() {
                packet_fields::resolved(prepared, &corpus["answers"][index(3)], profile.unwrap())
            } else {
                Ok(prepared.field)
            }
            .map(|mut f| {
                f.as_object_mut().unwrap().remove("id");
                f
            });
            let expected = &corpus["outputs"][index(4)];
            if actual.is_ok() != (expected["accepted"] == true)
                || actual.as_ref().is_ok_and(|v| v != &expected["field"])
                || resolution != expected["resolution"]
            {
                failures.push(format!(
                    "rewrite{} case{i}: actual{actual:?} resolution{resolution} expected{expected}",
                    mode["rewrite"]
                ));
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(4).collect::<Vec<_>>().join("\n")
    );
}
#[test]
fn generation_input_retains_revision_bounds_and_forbids_injected_authority_or_provider() {
    let data: Value =
        serde_json::from_str(include_str!("fixtures/packet-generation-corpus.json")).unwrap();
    for case in data["contracts"].as_array().unwrap() {
        let actual = packet_generation::request(case["input"].clone());
        assert_eq!(actual.is_ok(), case["accepted"] == true, "{case}");
        if let Ok(actual) = actual {
            assert_eq!(json!(actual), case["output"], "{case}");
        }
    }
}
