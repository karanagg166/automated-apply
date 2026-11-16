//! Deferred command-scope regressions: chat text cannot request focus, scripts, fill or submit.
use automated_apply_agents::browser_profiles::telegram_commands::{self, Command};
use uuid::Uuid;
#[test]
fn browser_command_aliases_keep_exact_packet_revision_and_never_accept_script_fill_focus_or_submission_actions()
 {
    let id = Uuid::from_u128(9);
    let bot = "fictional_bot";
    assert_eq!(
        telegram_commands::parse("/browser status", bot),
        Some(Command::Status)
    );
    assert_eq!(
        telegram_commands::parse("/chrome@FICTIONAL_BOT status", bot),
        Some(Command::Status)
    );
    assert_eq!(
        telegram_commands::parse("/browser@wrong_bot status", bot),
        Some(Command::Help)
    );
    assert!(telegram_commands::parse("/naukri status", bot).is_none());
    for action in ["open", "prepare", "pause", "resume", "cancel"] {
        for name in ["/browser", "/chrome"] {
            let command = Command::Action {
                action: action.into(),
                packet: id,
                revision: 3,
            };
            assert_eq!(
                telegram_commands::parse(&format!("{name} {action} {id} 3"), bot),
                Some(command.clone())
            );
            assert!(command.mutates());
        }
    }
    for action in [
        "fill", "submit", "apply", "script", "focus", "restore", "window", "settings",
    ] {
        assert_eq!(
            telegram_commands::parse(&format!("/browser {action} {id} 3"), bot),
            Some(Command::Help)
        );
    }
    for revision in [
        "0",
        "-1",
        "3.0",
        "three",
        "999999999999999999999999999999999",
    ] {
        assert_eq!(
            telegram_commands::parse(&format!("/browser open {id} {revision}"), bot),
            Some(Command::Help)
        );
    }
    assert_eq!(
        telegram_commands::parse("/browser open wrong-id 3", bot),
        Some(Command::Help)
    );
    assert_eq!(
        telegram_commands::parse(&format!("/browser open {id} 3 extra"), bot),
        Some(Command::Help)
    );
    assert!(!Command::Status.mutates());
    assert!(!Command::Help.mutates());
}
