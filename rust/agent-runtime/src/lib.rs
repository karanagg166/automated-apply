//! Specialist agents propose; the coordinator accounts, persists and fences execution.
//! Transports and model providers are separate from model-controlled contracts.
pub mod account_tokens;
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
pub mod discovery_schedule;
pub mod feed_ingestion;
mod job_catalog;
pub mod job_context;
pub mod knowledge;
pub mod missing_contract;
pub mod missing_store;
pub mod model_policy;
pub mod monthly;
pub mod notification_preferences;
mod notifications;
pub mod owner_proof;
pub mod packet_archive;
pub mod packet_context;
pub mod packet_contract;
pub mod packet_execution;
pub mod packet_fields;
pub mod packet_generation;
mod packet_mutation;
pub mod packet_mutation_contract;
pub mod packet_notice;
pub mod packet_platform;
pub mod packet_readiness;
pub mod packet_record;
pub mod packet_review;
pub mod packet_service;
pub mod packet_tracking;
pub mod packet_tracking_contract;
pub mod profile_confirmation;
pub mod profile_contract;
pub mod profile_store;
pub mod project_context;
pub mod provider;
pub mod provider_status;
pub mod public_discovery;
pub mod python_json;
pub mod saved_match;

pub mod knowledge_tools;
mod legacy_regex;

pub mod browser_inventory;
pub mod configuration;
mod gemini;
pub mod gmail_read;
pub mod google_oauth;
pub mod graph;
pub mod grounding;
pub mod http_policy;
pub mod lifecycle;
pub mod link_resolver;
pub mod local_socket;
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

pub mod mailboxes;

pub mod mail_evidence;

pub mod gmail_drafts;
