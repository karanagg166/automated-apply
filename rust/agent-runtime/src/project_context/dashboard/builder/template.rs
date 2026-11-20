//! Read bounded YAML frontmatter from an owner-configured local directory.

use super::{FILE_LIMIT, evidence, fact, sha256};
use crate::{Failure, Result, context_contract::python_space, resources::public_https};
use rustix::fs::{Mode, OFlags, open, openat};
use serde_json::Value;
use std::{
    fs::File,
    io::Read,
    path::{Component, Path},
};
use yaml_rust2::{
    Yaml, YamlLoader,
    parser::{Event, Parser, Tag},
};

const TOPICS: &[(&str, &str, bool)] = &[
    ("problem_solved", "overview", false),
    ("business_use_case", "business_use_case", false),
    ("architecture_hld", "architecture", false),
    ("frontend_technology", "frontend", false),
    ("backend_technology", "backend", false),
    ("database", "database", false),
    ("cache", "cache", false),
    ("queue_messaging", "queue", false),
    ("authentication_security", "authentication_security", false),
    ("deployment_infrastructure", "deployment", false),
    ("important_apis", "api", false),
    ("engineering_challenges", "challenge", true),
    ("personal_contribution", "contribution", true),
    ("verified_features", "feature", false),
    ("scaling_design_decisions", "design_decision", false),
    ("measured_outcomes", "measured_outcome", true),
    ("interview_talking_points", "interview", false),
];

fn read(root: &Path, relative: &str) -> Result<String> {
    let unsafe_path = Failure("unsafe_context_path");
    let unavailable = Failure("context_file_unreadable");
    let path = Path::new(relative);
    if !relative.starts_with("candidate_context/")
        || relative.contains('\\')
        || path.extension().and_then(|extension| extension.to_str()) != Some("md")
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(unsafe_path);
    }
    let no_follow = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK;
    let directory = no_follow | OFlags::DIRECTORY;
    let mut parent = open(root, directory, Mode::empty()).map_err(|_| unavailable)?;
    let mut parts = path.components().peekable();
    while let Some(Component::Normal(part)) = parts.next() {
        if parts.peek().is_some() {
            parent = openat(&parent, part, directory, Mode::empty()).map_err(|_| unavailable)?;
            continue;
        }
        let fd = openat(&parent, part, no_follow, Mode::empty()).map_err(|_| unavailable)?;
        let file = File::from(fd);
        let info = file.metadata().map_err(|_| unavailable)?;
        let size_error = Failure("context_file_missing_or_too_large");
        if !info.is_file() || info.len() > FILE_LIMIT as u64 {
            return Err(size_error);
        }
        let mut bytes = Vec::new();
        file.take(FILE_LIMIT as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| unavailable)?;
        if bytes.len() > FILE_LIMIT {
            return Err(size_error);
        }
        return String::from_utf8(bytes).map_err(|_| unavailable);
    }
    Err(unsafe_path)
}

fn parse(content: &str) -> Result<Yaml> {
    let invalid = Failure("invalid_context_yaml");
    let mut parser = Parser::new_from_str(content);
    let mut depth = 0usize;
    let mut documents = 0;
    let allowed_tag = |tag: Option<Tag>| {
        tag.is_none_or(|tag| {
            tag.handle == "tag:yaml.org,2002:"
                && matches!(
                    tag.suffix.as_str(),
                    "str" | "int" | "float" | "bool" | "null" | "map" | "seq"
                )
        })
    };
    for _ in 0..5000 {
        match parser.next_token().map_err(|_| invalid)?.0 {
            Event::StreamEnd => {
                let mut docs = YamlLoader::load_from_str(content).map_err(|_| invalid)?;
                if docs.len() == 1 {
                    return docs.pop().ok_or(invalid);
                }
                return Err(invalid);
            }
            Event::DocumentStart => {
                documents += 1;
                if documents > 1 {
                    return Err(invalid);
                }
            }
            Event::Alias(_) => return Err(Failure("yaml_aliases_not_supported")),
            Event::MappingStart(anchor, tag) | Event::SequenceStart(anchor, tag) => {
                check_node(anchor, allowed_tag(tag))?;
                depth += 1;
                if depth > 24 {
                    return Err(Failure("context_yaml_too_complex"));
                }
            }
            Event::Scalar(_, _, anchor, tag) => check_node(anchor, allowed_tag(tag))?,
            Event::MappingEnd | Event::SequenceEnd => {
                depth = depth.checked_sub(1).ok_or(invalid)?
            }
            _ => {}
        }
    }
    Err(Failure("context_yaml_too_complex"))
}

fn check_node(anchor: usize, tag_allowed: bool) -> Result<()> {
    if anchor != 0 {
        return Err(Failure("yaml_aliases_not_supported"));
    }
    if !tag_allowed {
        return Err(Failure("invalid_context_yaml"));
    }
    Ok(())
}

pub(super) fn facts(root: &Path, path: &str, name: &str) -> Result<Vec<Value>> {
    let source = read(root, path)?;
    let mut lines = source.lines();
    if lines.next() != Some("---") {
        return Err(Failure("project_frontmatter_required"));
    }
    let mut header = Vec::new();
    for line in &mut lines {
        if line == "---" {
            break;
        }
        header.push(line);
    }
    // A delimiter is required even when the header occupies the whole file.
    if header.len() + 2 > source.lines().count() {
        return Err(Failure("project_frontmatter_required"));
    }
    let doc = parse(&header.join("\n"))?;
    let fields = doc.as_hash().ok_or(Failure("invalid_project_context"))?;
    if let Some(project_name) = fields.get(&Yaml::String("project_name".into()))
        && !project_name.is_null()
        && !matches!(project_name.as_str(), Some(""))
        && project_name.as_str() != Some(name)
    {
        return Err(Failure("project_template_name_mismatch"));
    }
    let hash = sha256(&source);
    let lines = source.lines().count();
    let mut references = vec![evidence(path, None, &hash, 1, lines, None)];
    let invalid_references = Failure("invalid_project_references");
    if let Some(urls) = fields.get(&Yaml::String("references".into())) {
        let urls = urls
            .as_vec()
            .filter(|urls| urls.len() <= 9)
            .ok_or(invalid_references)?;
        for url in urls {
            let url = url
                .as_str()
                .and_then(public_https)
                .ok_or(invalid_references)?;
            references.push(evidence(path, None, &hash, 1, lines, Some(&url)));
        }
    }
    let mut facts = Vec::new();
    for (field, topic, personal) in TOPICS {
        let Some(value) = fields.get(&Yaml::String((*field).into())) else {
            continue;
        };
        if value.is_null() || value.as_vec().is_some_and(Vec::is_empty) {
            continue;
        }
        let unsafe_claim = Failure("unsafe_or_invalid_owner_claim");
        let text = value
            .as_str()
            .ok_or(unsafe_claim)?
            .trim_matches(python_space);
        if text.is_empty() {
            continue;
        }
        if text.chars().count() > 2000 || super::super::super::suspicious_text(text)? {
            return Err(unsafe_claim);
        }
        facts.push(fact(
            topic,
            text,
            "owner_supplied",
            &references,
            None,
            *personal,
        ));
    }
    Ok(facts)
}
