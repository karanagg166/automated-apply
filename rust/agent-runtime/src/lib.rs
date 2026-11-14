//! Specialist agents propose; the coordinator accounts, persists and fences execution.
//! Transports and model providers are separate from model-controlled contracts.
pub mod answer_contract;
pub mod answer_store;
pub mod context_contract;
pub mod contracts;
pub mod engine;
pub mod evidence_retrieval;
pub mod extractive;
pub mod postgres;
pub mod runner;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Failure(pub &'static str);
pub type Result<T> = std::result::Result<T, Failure>;
pub mod knowledge;
pub mod missing_contract;
pub mod model_policy;
pub mod monthly;
pub mod owner_proof;
pub mod profile_confirmation;
pub mod profile_contract;
pub mod profile_store;
pub mod project_context;
pub mod provider;
pub mod provider_status;
pub mod python_json;
pub mod saved_match;

pub mod knowledge_tools;
mod legacy_regex;

pub mod configuration;
pub mod graph;
pub mod grounding;
pub mod lifecycle;
pub mod link_resolver;
pub mod personal_facts;
pub mod planner;
pub mod process_lock;
pub mod question_classifier;
pub mod questions;
pub mod recovery;
pub mod resource_contract;
pub mod resource_store;
pub mod resources;
pub mod server;
pub mod telegram;
pub mod worker;
