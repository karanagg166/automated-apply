//! Deferred namespace/argument regression cases; command text cannot create an Apply grant.
use automated_apply_agents::execution::telegram_commands::{self, Command};
use uuid::Uuid;
#[test]
fn naukri_commands_keep_bot_namespace_bounded_jobs_and_preparation_controls_separate() {
    let id = Uuid::from_u128(7);
    let bot = "fictional_bot";
    let cases = [
        ("/naukri", Command::Status),
        ("/naukri status", Command::Status),
        ("/naukri@FICTIONAL_BOT queue", Command::Queue(None)),
        ("/naukri queue resume", Command::Queue(Some("start".into()))),
        ("/naukri queue stop", Command::Queue(Some("stop".into()))),
        (
            "/naukri automation start",
            Command::Automation("start".into()),
        ),
        ("/naukri find", Command::Find),
        ("/naukri@wrong_bot queue start", Command::Help),
        ("/naukri queue start unlimited", Command::Help),
        ("/naukri apply not-a-job", Command::Help),
        ("/naukri apply", Command::Help),
        ("/naukri reset quota", Command::Help),
    ];
    for (text, expected) in cases {
        assert_eq!(telegram_commands::parse(text, bot), Some(expected));
    }
    assert!(telegram_commands::parse("/agents start", bot).is_none());
    assert!(telegram_commands::parse("/naukriish queue start", bot).is_none());
    assert!(telegram_commands::parse("/chrome status", bot).is_none());
    let text = format!("/naukri apply {}", vec![id.to_string(); 25].join(" "));
    assert_eq!(
        telegram_commands::parse(&text, bot),
        Some(Command::Apply(vec![id; 25]))
    );
    let too_many = format!("{text} {id}");
    assert_eq!(
        telegram_commands::parse(&too_many, bot),
        Some(Command::Help)
    );
    let huge = format!("/naukri add {}", "x".repeat(2048));
    assert_eq!(telegram_commands::parse(&huge, bot), Some(Command::Help));
    for action in ["pause", "resume", "cancel"] {
        let text = format!("/naukri {action} {id}");
        assert_eq!(
            telegram_commands::parse(&text, bot),
            Some(Command::Control {
                action: action.into(),
                id
            })
        );
    }
    for command in [
        Command::Status,
        Command::Queue(None),
        Command::Find,
        Command::Help,
    ] {
        assert!(!command.mutates());
    }
    for command in [
        Command::Apply(vec![id]),
        Command::Queue(Some("start".into())),
        Command::Automation("stop".into()),
        Command::Control {
            action: "pause".into(),
            id,
        },
        Command::Add("https://www.naukri.com/job-listings-fictional-123456789012".into()),
    ] {
        assert!(command.mutates());
    }
}
