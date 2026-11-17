//! Deferred pure fixed-target checks. Targets are not transport or application grants.
use automated_apply_agents::{
    job_sources::plan::{Snapshot, Source},
    source_registry::Settings,
};
use serde_json::json;
use std::collections::BTreeMap;
fn settings(region: &str) -> Settings {
    Settings::from_values(&BTreeMap::from([
        (
            "GREENHOUSE_BOARDS".into(),
            json!({"zeta":"Fictional Zeta Employer","alpha":"Fictional Alpha Employer"})
                .to_string(),
        ),
        (
            "LEVER_BOARDS".into(),
            json!({"fictional":"Fictional Employer"}).to_string(),
        ),
        (
            "ASHBY_BOARDS".into(),
            json!({"fictional":"Fictional Employer"}).to_string(),
        ),
        (
            "SMARTRECRUITERS_BOARDS".into(),
            json!({"fictional":"Fictional Employer"}).to_string(),
        ),
        ("LEVER_REGION".into(), region.into()),
    ]))
    .unwrap()
}
#[test]
fn seven_public_sources_build_only_fixed_documented_origins_and_query_fields() {
    let source_settings = settings("global");
    for (source, url, params) in [
        (
            Source::Remotive,
            "https://remotive.com/api/remote-jobs",
            vec![
                ("category", "software-dev"),
                ("limit", "40"),
                ("search", "Rust Tokio"),
            ],
        ),
        (
            Source::Arbeitnow,
            "https://www.arbeitnow.com/api/job-board-api",
            vec![("page", "2")],
        ),
        (
            Source::HackerNews,
            "https://hn.algolia.com/api/v1/search_by_date",
            vec![("tags", "story,author_whoishiring"), ("hitsPerPage", "10")],
        ),
    ] {
        let plan = Snapshot::build(
            &source_settings,
            source,
            json!({"page":2,"limit":20,"keywords":["Rust","Tokio"]}),
        )
        .unwrap();
        let target = plan.root().unwrap();
        assert_eq!(target.url(), url);
        assert_eq!(
            target.query(),
            params
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect::<Vec<_>>()
        );
        assert_eq!(plan.source(), source);
        assert_eq!(plan.board_count(), 0);
    }
    for (source, url, params) in [
        (
            Source::Greenhouse,
            "https://boards-api.greenhouse.io/v1/boards/alpha/jobs",
            vec![("content", "true")],
        ),
        (
            Source::Lever,
            "https://api.lever.co/v0/postings/fictional",
            vec![("mode", "json")],
        ),
        (
            Source::Ashby,
            "https://api.ashbyhq.com/posting-api/job-board/fictional",
            vec![("includeCompensation", "true")],
        ),
        (
            Source::Smartrecruiters,
            "https://api.smartrecruiters.com/v1/companies/fictional/postings",
            vec![("offset", "20"), ("limit", "10")],
        ),
    ] {
        let plan = Snapshot::build(&source_settings, source, json!({"page":2,"limit":20})).unwrap();
        let target = plan.board(0, 20, 10).unwrap();
        assert_eq!(target.url(), url);
        assert_eq!(
            target.query(),
            params
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect::<Vec<_>>()
        );
        assert!(plan.root().is_err());
    }
    let plan = Snapshot::build(&source_settings, Source::Greenhouse, json!({})).unwrap();
    assert_eq!(plan.board_count(), 2);
    assert!(plan.board(1, 0, 20).unwrap().url().contains("/zeta/"));
    let eu = settings("eu");
    let plan = Snapshot::build(&eu, Source::Lever, json!({})).unwrap();
    assert_eq!(
        plan.board(0, 0, 20).unwrap().url(),
        "https://api.eu.lever.co/v0/postings/fictional"
    );
}
#[test]
fn source_request_bounds_refuse_missing_boards_unknown_sources_and_unbounded_continuations() {
    let empty = Settings::from_values(&BTreeMap::new()).unwrap();
    for source in [
        Source::Greenhouse,
        Source::Lever,
        Source::Ashby,
        Source::Smartrecruiters,
    ] {
        assert!(Snapshot::build(&empty, source, json!({})).is_err());
    }
    assert!(Snapshot::build(&empty, Source::Remotive, json!({"page":11,"limit":100})).is_err());
    assert!(Snapshot::build(&empty, Source::Remotive, json!({"page":10,"limit":100})).is_ok());
    for source in [
        "instahyre",
        "https://private-fixture.example",
        "",
        "greenhouse/else",
    ] {
        assert!(Source::parse(source).is_err());
    }
    let plan = Snapshot::build(
        &settings("global"),
        Source::Smartrecruiters,
        json!({"page":2,"limit":20}),
    )
    .unwrap();
    assert_eq!(
        plan.detail(0, "12345").unwrap().url(),
        "https://api.smartrecruiters.com/v1/companies/fictional/postings/12345"
    );
    for id in [
        "../private",
        "id_with_underscore",
        "12345?token=private",
        "",
        "12345/else",
    ] {
        assert!(plan.detail(0, id).is_err());
    }
    assert!(plan.detail(1, "12345").is_err());
    assert!(plan.board(0, 21, 20).is_err());
    assert!(plan.board(0, 0, 21).is_err());
    assert!(plan.board(0, 0, 0).is_err());
    assert!(plan.comments("98765").is_err());
    let hn = Snapshot::build(&empty, Source::HackerNews, json!({"page":2,"limit":20})).unwrap();
    let target = hn.comments("98765").unwrap();
    assert_eq!(target.url(), "https://hn.algolia.com/api/v1/search");
    assert_eq!(
        target.query(),
        &[
            ("tags".into(), "comment,story_98765".into()),
            ("hitsPerPage".into(), "20".into()),
            ("page".into(), "1".into()),
            ("numericFilters".into(), "parent_id=98765".into())
        ]
    );
    for id in ["９８７６５", "../private", "98765,else", ""] {
        assert!(hn.comments(id).is_err());
    }
}
#[test]
fn source_context_binds_sorted_employer_identity_and_effective_region_without_provider_authority() {
    let global = settings("global");
    let eu = settings("eu");
    let a = Snapshot::build(&global, Source::Lever, json!({})).unwrap();
    let b = Snapshot::build(&eu, Source::Lever, json!({})).unwrap();
    assert_ne!(a.context(), b.context());
    assert_eq!(a.context().len(), 64);
    let a = Snapshot::build(&global, Source::Remotive, json!({})).unwrap();
    let b = Snapshot::build(&eu, Source::Remotive, json!({})).unwrap();
    assert_eq!(a.context(), b.context());
    let changed = Settings::from_values(&BTreeMap::from([(
        "LEVER_BOARDS".into(),
        json!({"fictional":"Different Fictional Employer"}).to_string(),
    )]))
    .unwrap();
    let a = Snapshot::build(&global, Source::Lever, json!({})).unwrap();
    let b = Snapshot::build(&changed, Source::Lever, json!({})).unwrap();
    assert_ne!(a.context(), b.context());
    assert_eq!(Source::Remotive.interval_seconds(), 21600);
    for source in [
        Source::Greenhouse,
        Source::Lever,
        Source::Ashby,
        Source::Smartrecruiters,
        Source::Arbeitnow,
        Source::HackerNews,
    ] {
        assert_eq!(source.interval_seconds(), 60);
        assert_eq!(Source::parse(source.name()).unwrap(), source);
    }
}
