//! Specialist agents propose; the coordinator accounts, persists and fences execution.
//! Transports and model providers are separate from model-controlled contracts.
pub mod contracts;
pub mod engine;
pub mod postgres;
pub mod runner;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Failure(pub &'static str);
pub type Result<T> = std::result::Result<T, Failure>;
pub mod knowledge;
pub mod monthly;
pub mod provider;

pub mod knowledge_tools;

pub mod configuration;
pub mod lifecycle;
pub mod planner;
pub mod process_lock;
pub mod questions;
pub mod server;
pub mod worker;
