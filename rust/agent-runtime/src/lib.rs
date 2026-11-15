//! Specialist agents propose; the coordinator accounts, persists and fences execution.
//! Transports and model providers are separate from model-controlled contracts.
pub mod answer_context;
pub mod answer_contract;
pub mod answer_direct;
pub mod answer_reuse;
pub mod answer_service;
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
mod job_catalog;
pub mod job_context;
pub mod knowledge;
pub mod missing_contract;
pub mod missing_store;
pub mod model_policy;
pub mod monthly;
mod notifications;
pub mod owner_proof;
pub mod packet_contract;
pub mod packet_fields;
pub mod packet_platform;
pub mod packet_readiness;
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

pub mod browser_inventory;
pub mod configuration;
mod gemini;
pub mod graph;
pub mod grounding;
pub mod lifecycle;
pub mod link_resolver;
pub mod mcp_bridge;
mod ollama;
pub mod personal_facts;
pub mod planner;
pub mod private_resume;
pub mod process_lock;
pub mod question_classifier;
pub mod questions;
pub mod recovery;
pub mod resource_contract;
pub mod resource_store;
pub mod resources;
pub mod resume_suggestions;
pub mod server;
pub mod telegram;
pub mod tool_api;
pub mod worker;
