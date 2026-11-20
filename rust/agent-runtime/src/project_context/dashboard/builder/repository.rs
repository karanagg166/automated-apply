//! Static evidence from regular blobs in one authorized local Git commit.

use super::{FILE_LIMIT, Settings, evidence, fact, sha256};
use crate::{
    Failure, Result,
    project_context::{conversation::compact, suspicious_text},
    python_json::digest,
};
use automated_apply_domain::text::folded;
use regex::Regex;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    path::Path,
    process::Stdio,
    sync::LazyLock,
    time::Duration,
};
use tokio::{io::AsyncReadExt, process::Command};

const MANIFESTS: &[&str] = &[
    "package.json",
    "requirements.txt",
    "requirements-runtime.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
];
const TOTAL_LIMIT: usize = 768 * 1024;
const MAX_FILES: usize = 24;
const UNAVAILABLE: Failure = Failure("repository_not_authorized_or_unavailable");
const READ_FAILED: Failure = Failure("repository_read_failed_or_too_large");

pub(super) fn valid_url(url: &str) -> bool {
    static REPOSITORY: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\Ahttps://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\z")
            .expect("repository URL regex")
    });
    url.len() <= 2048 && REPOSITORY.is_match(url)
}

fn technology(name: &str) -> Option<&'static str> {
    Some(match name {
        "react" => "React",
        "next" => "Next.js",
        "typescript" => "TypeScript",
        "express" => "Express",
        "fastapi" => "FastAPI",
        "sqlalchemy" => "SQLAlchemy",
        "asyncpg" | "psycopg" | "pg" => "PostgreSQL",
        "redis" => "Redis",
        "bullmq" => "BullMQ",
        "prisma" => "Prisma",
        "mongoose" | "pymongo" => "MongoDB",
        "django" => "Django",
        "flask" => "Flask",
        "celery" => "Celery",
        "pydantic" => "Pydantic",
        "@supabase/supabase-js" => "Supabase",
        "socket.io" | "socket.io-client" => "Socket.IO",
        "razorpay" => "Razorpay",
        "qdrant-client" => "Qdrant",
        "dramatiq" => "Dramatiq",
        "langchain" => "LangChain",
        "pgvector" => "pgvector",
        "pytesseract" => "Tesseract OCR",
        _ => return None,
    })
}

fn is_test(name: &str) -> bool {
    name.starts_with("test_") || name.contains(".test.") || name.contains(".spec.")
}

fn filename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

fn readme(path: &str) -> bool {
    filename(path).to_ascii_lowercase().starts_with("readme")
}

fn allowed_path(path: &str) -> bool {
    if path.chars().count() > 240 || path.contains('\\') || path.chars().any(char::is_control) {
        return false;
    }
    let banned = |part: &str| {
        part.is_empty()
            || part.starts_with('.')
            || matches!(
                part,
                "node_modules" | "vendor" | "dist" | "secrets" | "fixtures"
            )
            || ["credential", "private", "secret", "token"]
                .iter()
                .any(|word| part.to_ascii_lowercase().contains(word))
    };
    if path.split('/').any(banned) {
        return false;
    }
    let root = path.split('/').next().unwrap_or_default();
    let extension = path.rsplit_once('.').map_or("", |(_, suffix)| suffix);
    let name = filename(path);
    MANIFESTS.contains(&name)
        || readme(path)
        || (matches!(extension, "md" | "sql" | "prisma")
            && matches!(root, "docs" | "schema" | "prisma" | "migrations"))
        || (matches!(extension, "py" | "ts" | "tsx" | "js" | "go" | "java" | "rs")
            && matches!(
                root,
                "src" | "app" | "apps" | "backend" | "frontend" | "socket-server" | "e2e" | "tests"
            )
            && (!path.split('/').any(|part| part == "tests") || is_test(name)))
}

fn sha(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

async fn git(root: &Path, args: &[&str], limit: usize) -> Result<Vec<u8>> {
    let mut child = Command::new("/usr/bin/git")
        .current_dir(root)
        .args([
            "--no-pager",
            "-c",
            "protocol.allow=never",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
        ])
        .args(args)
        .env_clear()
        .envs([
            ("PATH", "/usr/bin:/bin"),
            ("GIT_CONFIG_SYSTEM", "/dev/null"),
            ("GIT_CONFIG_GLOBAL", "/dev/null"),
            ("GIT_CONFIG_NOSYSTEM", "1"),
            ("GIT_NO_LAZY_FETCH", "1"),
            ("GIT_ALLOW_PROTOCOL", ""),
            ("GIT_NO_REPLACE_OBJECTS", "1"),
            ("GIT_OPTIONAL_LOCKS", "0"),
            ("GIT_TERMINAL_PROMPT", "0"),
            ("LC_ALL", "C"),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| READ_FAILED)?;
    tokio::time::timeout(Duration::from_secs(8), async {
        let mut bytes = Vec::new();
        child
            .stdout
            .take()
            .ok_or(READ_FAILED)?
            .take(limit as u64 + 1)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| READ_FAILED)?;
        if bytes.len() > limit || !child.wait().await.map_err(|_| READ_FAILED)?.success() {
            return Err(READ_FAILED);
        }
        Ok(bytes)
    })
    .await
    .map_err(|_| READ_FAILED)?
}

async fn git_text(root: &Path, args: &[&str], limit: usize) -> Result<String> {
    String::from_utf8(git(root, args, limit).await?).map_err(|_| READ_FAILED)
}

async fn snapshot(settings: &Settings, url: &str) -> Result<(String, BTreeMap<String, String>)> {
    let url = url.trim_end_matches('/');
    let configured = settings.checkouts.get(url).cloned().ok_or(UNAVAILABLE)?;
    let root = tokio::task::spawn_blocking(move || {
        let root = std::fs::canonicalize(&configured).map_err(|_| UNAVAILABLE)?;
        if root != configured || !root.is_dir() {
            return Err(UNAVAILABLE);
        }
        Ok(root)
    })
    .await
    .map_err(|_| UNAVAILABLE)??;
    let location = git_text(&root, &["rev-parse", "--show-toplevel"], 4096).await?;
    if Path::new(location.trim_end_matches('\n')) != root {
        return Err(UNAVAILABLE);
    }
    let origin = git_text(
        &root,
        &[
            "config",
            "--local",
            "--no-includes",
            "--get",
            "remote.origin.url",
        ],
        4096,
    )
    .await?;
    let origin = origin.trim_end_matches('\n').trim_end_matches('/');
    let origin = origin.strip_suffix(".git").unwrap_or(origin);
    let ssh_path = url.strip_prefix("https://github.com/").ok_or(UNAVAILABLE)?;
    if origin != url && origin.strip_prefix("git@github.com:") != Some(ssh_path) {
        return Err(Failure("repository_origin_mismatch"));
    }
    let commit = git_text(&root, &["rev-parse", "--verify", "HEAD^{commit}"], 64).await?;
    let commit = commit.trim_end_matches('\n');
    if !sha(commit) {
        return Err(Failure("repository_revision_invalid"));
    }
    let entries = git(
        &root,
        &["ls-tree", "-r", "--long", "-z", "--full-tree", commit],
        1024 * 1024,
    )
    .await?;
    let mut candidates = Vec::new();
    for entry in entries.split(|byte| *byte == 0) {
        let Ok(entry) = std::str::from_utf8(entry) else {
            continue;
        };
        let Some((metadata, path)) = entry.split_once('\t') else {
            continue;
        };
        if !allowed_path(path) {
            continue;
        }
        let mut metadata = metadata.split_ascii_whitespace();
        if !matches!(metadata.next(), Some("100644" | "100755")) || metadata.next() != Some("blob")
        {
            continue;
        }
        let (Some(blob), Some(size)) = (
            metadata.next().filter(|id| sha(id)),
            metadata
                .next()
                .and_then(|size| size.parse::<usize>().ok())
                .filter(|size| *size <= FILE_LIMIT),
        ) else {
            continue;
        };
        candidates.push((path, blob, size));
    }
    candidates
        .sort_by_key(|(path, _, _)| (!MANIFESTS.contains(&filename(path)), !readme(path), *path));
    let mut files = BTreeMap::new();
    let mut total = 0;
    for (path, blob, size) in candidates {
        if files.len() == MAX_FILES || total + size > TOTAL_LIMIT {
            break;
        }
        let content = git_text(&root, &["cat-file", "blob", blob], size).await?;
        if content.len() != size {
            return Err(READ_FAILED);
        }
        files.insert(path.to_owned(), content);
        total += size;
    }
    Ok((commit.to_owned(), files))
}

fn dependencies(name: &str, content: &str) -> BTreeSet<String> {
    let mut result = BTreeSet::new();
    if name == "package.json"
        && let Ok(manifest) = serde_json::from_str::<Value>(content)
    {
        for field in ["dependencies", "devDependencies"] {
            if let Some(items) = manifest[field].as_object() {
                result.extend(items.keys().cloned());
            }
        }
    } else if name.starts_with("requirements") {
        static REQUIREMENT: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"^([a-zA-Z][\w.-]*)\s*(?:[<=>~!]|$)").expect("requirements expression")
        });
        result.extend(
            content
                .lines()
                .filter_map(|line| REQUIREMENT.captures(line.trim()))
                .map(|capture| folded(&capture[1])),
        );
    } else if name == "pyproject.toml"
        && let Ok(manifest) = content.parse::<toml::Table>()
    {
        if let Some(items) = manifest
            .get("project")
            .and_then(|project| project.get("dependencies"))
            .and_then(toml::Value::as_array)
        {
            result.extend(items.iter().filter_map(toml::Value::as_str).map(|item| {
                folded(
                    item.split(['<', '=', '>', '~', '!', '[', ';', ' '])
                        .next()
                        .unwrap_or_default(),
                )
            }));
        }
        if let Some(items) = manifest
            .get("tool")
            .and_then(|tool| tool.get("poetry"))
            .and_then(|poetry| poetry.get("dependencies"))
            .and_then(toml::Value::as_table)
        {
            result.extend(items.keys().cloned());
        }
    }
    result
}

fn imports(path: &str) -> Option<&'static Regex> {
    static PYTHON: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^\s*(?:from|import)\s+([a-zA-Z][\w-]*)(?:[. ,]|$)")
            .expect("Python import expression")
    });
    static JAVASCRIPT: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r#"^\s*import\s+(?:.+?\s+from\s+)?['"]([@\w/-]+)['"]"#)
            .expect("JavaScript import expression")
    });
    match path.rsplit_once('.').map(|(_, extension)| extension) {
        Some("py") => Some(&PYTHON),
        Some("js" | "ts" | "tsx") => Some(&JAVASCRIPT),
        _ => None,
    }
}

fn collect(
    commit: &str,
    files: &BTreeMap<String, String>,
    owner: Vec<Value>,
) -> Result<Vec<Value>> {
    let mut facts = Vec::new();
    let mut seen = HashSet::new();
    let mut add = |item: Value| {
        if seen.insert(item["id"].as_str().unwrap_or_default().to_owned()) {
            facts.push(item);
        }
        facts.len() == 100
    };
    'files: for (path, content) in files {
        let hash = sha256(content);
        let reference = [evidence(path, Some(commit), &hash, 1, 1, None)];
        let name = filename(path);
        if is_test(name) {
            if add(fact(
                "feature",
                &format!(
                    "The repository contains test source {path}; execution and coverage percentages are not verified."
                ),
                "direct",
                &reference,
                None,
                false,
            )) {
                break;
            }
            continue;
        }
        for name in dependencies(name, content) {
            if let Some(technology) = technology(&name)
                && add(fact(
                    "technology",
                    &format!("The repository declares {technology} as a dependency."),
                    "direct",
                    &reference,
                    Some(technology),
                    false,
                ))
            {
                break 'files;
            }
        }
        if readme(path) {
            let prose = content
                .lines()
                .filter(|line| {
                    !line.trim().is_empty()
                        && !line.starts_with(['#', '!', '<'])
                        && !line.starts_with("```")
                })
                .collect::<Vec<_>>()
                .join(" ");
            if !prose.is_empty()
                && !suspicious_text(&prose)?
                && add(fact(
                    "overview",
                    &compact(&prose, 80, 1000),
                    "inferred",
                    &reference,
                    None,
                    false,
                ))
            {
                break;
            }
        }
        if let Some(import) = imports(path) {
            for (number, line) in content.lines().take(100_000).enumerate() {
                if let Some(module) = import.captures(line)
                    && let Some(technology) = technology(&folded(&module[1]))
                    && add(fact(
                        "technology",
                        &format!("Source code imports {technology}."),
                        "direct",
                        &[evidence(
                            path,
                            Some(commit),
                            &hash,
                            number + 1,
                            number + 1,
                            None,
                        )],
                        Some(technology),
                        false,
                    ))
                {
                    break 'files;
                }
            }
        }
    }
    for item in owner.into_iter().take(100 - facts.len()) {
        // Owner facts are produced by the template reader and retain that provenance.
        if seen.insert(item["id"].as_str().unwrap_or_default().to_owned()) {
            facts.push(item);
        }
    }
    Ok(facts)
}

pub(super) async fn build(
    settings: &Settings,
    project: &Value,
    url: &str,
    owner: Vec<Value>,
) -> Result<super::Evidence> {
    let (commit, files) = snapshot(settings, url).await?;
    let facts = collect(&commit, &files, owner)?;
    let declared: HashSet<_> = facts
        .iter()
        .filter(|fact| fact["verification"] == "direct")
        .filter_map(|fact| fact["technology"].as_str())
        .map(folded)
        .collect();
    let unsupported = project["tech_stack"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .filter(|tech| !declared.contains(&folded(tech)))
        .map(str::to_owned)
        .collect();
    let source_hash = digest(&json!(files));
    let revision = digest(
        &json!({"configuration":project,"commit_sha":commit,"source_hash":source_hash,"facts":facts}),
    );
    Ok(super::Evidence {
        commit: Some(commit),
        source_hash,
        facts,
        unsupported,
        revision,
    })
}
