//! Deferred private-owner command syntax and context isolation.
use automated_apply_agents::telegram_local::{self, Command};
#[test]
fn legacy_owner_commands_preserve_preview_and_context_only_effects() {
    let bot = "fictional_bot";
    for (text, want) in [
        ("/status", Command::Status),
        (" /connections@FICTIONAL_BOT ", Command::Connections),
        ("/jobs", Command::Jobs),
        ("/reset", Command::Reset),
        (
            "/apply https://wellfound.com/jobs/fictional?private=query",
            Command::Preview("https://wellfound.com/jobs/fictional?private=query".into()),
        ),
        ("/start aa_0123456789abcdef01234567", Command::Help),
        ("/reset@wrong_bot", Command::Help),
        ("/reset everything", Command::Help),
        ("/apply", Command::Help),
        ("/apply http://example.com/job", Command::Help),
        ("/apply https://127.0.0.1/job", Command::Help),
        ("/apply https://user:secret@example.com/job", Command::Help),
        ("/apply https://example.com/job extra", Command::Help),
    ] {
        assert_eq!(telegram_local::parse(text, bot), Some(want), "{text}");
    }
    for text in [
        "/agents runs",
        "/naukri apply",
        "/browser status",
        "/reset_quota",
        "find jobs",
    ] {
        assert_eq!(telegram_local::parse(text, bot), None);
    }
    assert_eq!(
        telegram_local::parse(
            &format!("/apply https://example.com/{}", "x".repeat(2048)),
            bot
        ),
        Some(Command::Help)
    );
    assert!(Command::Reset.mutates());
    assert!(Command::Preview("https://example.com/".into()).mutates());
    for command in [
        Command::Status,
        Command::Connections,
        Command::Jobs,
        Command::Help,
    ] {
        assert!(!command.mutates());
    }
}
#[test]
fn telegram_selection_memory_uses_actual_legacy_owner_key_without_codex_identity() {
    use std::{
        io::Write,
        path::Path,
        process::{Command as Process, Stdio},
    };
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,hashlib,json,types
from pathlib import Path
tree=ast.parse(Path('backend/app/local_agent/memory.py').read_text())
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='context_key')
ns={'hashlib':hashlib}
exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-context-key>','exec'),ns)
print(json.dumps([ns['context_key'](types.SimpleNamespace(identity=str(n))) for n in [1,11,1234567890123]]))
"#;
    let mut child = Process::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(script.as_bytes())
        .unwrap();
    let result = child.wait_with_output().unwrap();
    assert!(result.status.success());
    let expected: Vec<String> = serde_json::from_slice(&result.stdout).unwrap();
    for (owner, want) in [1, 11, 1234567890123].into_iter().zip(expected) {
        assert_eq!(telegram_local::context_key(owner), want);
        assert!(!want.contains("agent_conversation"));
    }
}
