use automated_apply_domain::{matching::*, text::*};
use serde_json::json;
#[test]
fn published_aliases_do_not_infer_other_skills() {
    assert_eq!(skill_key(" React.js "), "react");
    assert_eq!(skill_key("Fast API"), "fastapi");
    assert_ne!(skill_key("Java"), skill_key("JavaScript"));
    assert!(!bounded_skill_present("c", "c++ c# objectivec"));
    assert!(bounded_skill_present("c++", "use c++ now"));
}
#[test]
fn role_qualifier_is_removed_only_for_software_families() {
    assert_eq!(title_key("Backend Web Developer"), "backend developer");
    assert_eq!(title_key("Full—Stack Engineer"), "full stack engineer");
    assert_eq!(title_key("Sales Web Developer"), "sales web developer");
    assert_ne!(title_key("Backend Design Developer"), "backend developer");
}
#[test]
fn unknown_experience_does_not_gain_seniority_points() {
    let job = Listing {
        title: "Rust Developer".into(),
        skills_required: vec!["Rust".into()],
        ..Listing::default()
    };
    let profile = Profile {
        verified_skills: vec!["Rust".into()],
        ..Profile::default()
    };
    let result = base_match(&job, &profile);
    assert_eq!(result.match_score, 40.0);
    assert!(result.explanation.contains("Experience is unknown"));
    assert!(
        discovery_match(&job, &profile, None, false)
            .unknown_fields
            .contains(&"experience_suitability".into())
    );
}
#[test]
fn unknown_company_stage_never_becomes_startup_evidence() {
    let job = Listing::default();
    let profile = Profile {
        preferences: Preferences {
            prioritize_startups: Some(true),
            company_stages: vec!["seed".into()],
            ..Preferences::default()
        },
        ..Profile::default()
    };
    let result = discovery_match(
        &job,
        &profile,
        Some(&Company {
            name: "Fictional Company".into(),
            ..Company::default()
        }),
        false,
    );
    assert!(result.unknown_fields.contains(&"startup_status".into()));
    assert!(result.unknown_fields.contains(&"company_stage".into()));
}
#[test]
fn history_exclusion_overrides_a_perfect_match() {
    let job = Listing {
        title: "Rust Developer".into(),
        skills_required: vec!["Rust".into()],
        is_remote: true,
        remote_type: "remote".into(),
        experience_level: Some("junior".into()),
        ..Listing::default()
    };
    let profile = Profile {
        verified_skills: vec!["Rust".into()],
        verified_experience_years: Some(0.0),
        preferences: Preferences {
            target_titles: vec!["Rust Developer".into()],
            remote_preference: Some("remote".into()),
            ..Preferences::default()
        },
    };
    assert_eq!(
        discovery_match(&job, &profile, None, false).match_score,
        100.0
    );
    assert_eq!(discovery_match(&job, &profile, None, true).match_score, 0.0);
}
#[test]
fn profile_validation_retains_first_equivalent_verified_fact() {
    let profile: Profile =
        serde_json::from_value(json!({"verified_skills":["ος","οσ","React", " React  "]})).unwrap();
    assert_eq!(profile.verified_skills, vec!["ος", "React"]);
    assert!(serde_json::from_value::<Profile>(json!({"verified_skills":[""]})).is_err());
}
#[test]
fn unicode_final_sigma_and_casefold_are_distinct() {
    assert_eq!(lowered("ΟΣ"), "ος");
    assert_eq!(lowered("ΟΣΑ"), "οσα");
    assert_eq!(folded("ΟΣ"), "οσ");
    assert_eq!(folded("Straße"), "strasse");
}
#[test]
fn html_decoding_preserves_legacy_numeric_and_named_semantics() {
    assert_eq!(unescape_html("&#82;ust &notit; &#x80;"), "Rust ¬it; €");
    assert_eq!(
        unescape_html("&#0; &#xD800; &#9999999999999999999999;"),
        "� � �"
    );
    assert_eq!(
        description_text("<p>C&#43;&#43; &amp; Rust</p>"),
        " c++ & rust "
    );
}
