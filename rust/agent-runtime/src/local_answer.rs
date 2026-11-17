//! Versioned local-answer provenance and transient coalescing. No configuration, DB or model startup.
use crate::{
    Failure, Result,
    extractive::{self, Instructions},
    grounding::{Fact, ModelAnswer},
    rearranger::Plan,
};
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    future::Future,
    pin::Pin,
    sync::{Arc, Mutex},
};
use tokio::{sync::watch, task::AbortHandle};
use uuid::Uuid;
#[derive(Clone, Copy, Serialize)]
pub struct Usage {
    pub input_tokens: Option<u32>,
    pub output_tokens: Option<u32>,
}
#[derive(Clone, Serialize)]
pub struct SafeAnswer {
    pub(crate) source: &'static str,
    pub(crate) content: Option<ModelAnswer>,
    pub(crate) missing_information: Vec<String>,
    pub(crate) error_code: Option<&'static str>,
    pub(crate) model_attempted: bool,
    pub(crate) usage: Option<Usage>,
    pub(crate) contract_version: &'static str,
}
impl SafeAnswer {
    pub fn source(&self) -> &'static str {
        self.source
    }
    pub fn content(&self) -> Option<&ModelAnswer> {
        self.content.as_ref()
    }
    pub fn error_code(&self) -> Option<&'static str> {
        self.error_code
    }
    pub fn model_attempted(&self) -> bool {
        self.model_attempted
    }
    pub fn status(&self) -> &'static str {
        if self.content.is_some() {
            "draft_ready"
        } else {
            self.source
        }
    }
    pub fn used_llm(&self) -> bool {
        self.source == "ollama_generated_verified"
    }
    fn empty(source: &'static str) -> Self {
        Self {
            source,
            content: None,
            missing_information: vec![],
            error_code: None,
            model_attempted: false,
            usage: None,
            contract_version: "local_answer.v1",
        }
    }
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Route {
    Narrative,
    FactualExtraction,
    ApprovedSummary,
    ProfileLink,
    ResumeStatus,
}
#[derive(Clone, Copy)]
pub struct Options {
    pub rewrite: bool,
    pub low_memory: bool,
    pub route: Route,
}
struct Resolution {
    answer: SafeAnswer,
    clauses: usize,
}
fn resolve(
    question: &str,
    context: &Value,
    limits: Instructions,
    route: Route,
) -> Result<Resolution> {
    if matches!(route, Route::ProfileLink | Route::ResumeStatus) {
        let mut answer = SafeAnswer::empty("needs_input");
        answer.missing_information =
            vec!["Resolve using the existing profile/resume resolver.".into()];
        return Ok(Resolution { answer, clauses: 0 });
    }
    let prepared = extractive::prepare(question, context, limits)?;
    if !prepared.missing.is_empty() {
        let mut answer = SafeAnswer::empty("needs_input");
        answer.missing_information = prepared.missing;
        return Ok(Resolution { answer, clauses: 0 });
    }
    if let Some(error) = prepared.error {
        let mut answer = SafeAnswer::empty("validation_failed");
        answer.error_code = Some(error);
        return Ok(Resolution { answer, clauses: 0 });
    }
    let facts: Vec<Fact> = serde_json::from_value(context["evidence"].clone())
        .map_err(|_| Failure("invalid_verified_context"))?;
    let text = prepared
        .clauses
        .iter()
        .map(|c| c.text.as_str())
        .collect::<Vec<_>>()
        .join(" ");
    let (content, error) = extractive::match_answer(&text, &prepared, &facts, limits)?;
    let clauses = prepared.clauses.len();
    let mut answer = SafeAnswer::empty(if error.is_some() {
        "validation_failed"
    } else {
        "deterministic_extractive"
    });
    answer.content = content;
    answer.error_code = error;
    Ok(Resolution { answer, clauses })
}
pub(crate) fn deterministic(
    question: &str,
    context: &Value,
    limits: Instructions,
    route: Route,
) -> Result<SafeAnswer> {
    Ok(resolve(question, context, limits, route)?.answer)
}
pub struct Rewrite {
    pub answer: String,
    pub usage: Option<Usage>,
}
pub struct RewriteFailure {
    pub failure: Failure,
    pub usage: Option<Usage>,
}
/// Implementations perform bounded transport only. Reserve/persist outside this cancellable callback.
pub trait Rewriter: Send + Sync {
    fn rewrite(
        &self,
        permitted_payload: Value,
    ) -> Pin<Box<dyn Future<Output = std::result::Result<Rewrite, RewriteFailure>> + Send>>;
}
struct Entry {
    nonce: Uuid,
    waiters: usize,
    receiver: watch::Receiver<Option<Arc<SafeAnswer>>>,
    abort: AbortHandle,
}
type Flights = Arc<Mutex<BTreeMap<String, Entry>>>;
struct Waiter {
    flights: Flights,
    key: String,
    nonce: Uuid,
}
impl Drop for Waiter {
    fn drop(&mut self) {
        let Ok(mut flights) = self.flights.lock() else {
            return;
        };
        let Some(entry) = flights.get_mut(&self.key).filter(|e| e.nonce == self.nonce) else {
            return;
        };
        entry.waiters -= 1;
        if entry.waiters == 0 {
            if let Some(entry) = flights.remove(&self.key) {
                entry.abort.abort();
            }
        }
    }
}
#[derive(Clone, Default)]
pub struct Engine {
    rewriter: Option<Arc<dyn Rewriter>>,
    flights: Flights,
}
impl Engine {
    pub fn with_rewriter(rewriter: Arc<dyn Rewriter>) -> Self {
        Self {
            rewriter: Some(rewriter),
            flights: Default::default(),
        }
    }
    pub async fn answer(
        &self,
        question: &str,
        context: &Value,
        instructions: &Value,
        options: Options,
    ) -> Result<SafeAnswer> {
        if matches!(options.route, Route::ProfileLink | Route::ResumeStatus) {
            return Ok(resolve(
                question,
                context,
                Instructions {
                    max_characters: 1,
                    max_words: None,
                },
                options.route,
            )?
            .answer);
        }
        let characters = instructions["max_characters"]
            .as_u64()
            .filter(|n| (1..=10000).contains(n))
            .ok_or(Failure("invalid_answer_request"))? as usize;
        let words = if instructions["max_words"].is_null() {
            None
        } else {
            Some(
                instructions["max_words"]
                    .as_u64()
                    .filter(|n| (1..=2000).contains(n))
                    .ok_or(Failure("invalid_answer_request"))? as usize,
            )
        };
        let resolved = resolve(
            question,
            context,
            Instructions {
                max_characters: characters,
                max_words: words,
            },
            options.route,
        )?;
        let fallback = resolved.answer;
        if fallback.content.is_none()
            || !options.rewrite
            || options.low_memory
            || matches!(
                options.route,
                Route::FactualExtraction
                    | Route::ApprovedSummary
                    | Route::ProfileLink
                    | Route::ResumeStatus
            )
            || resolved.clauses < 2
        {
            return Ok(fallback);
        }
        let Some(rewriter) = self.rewriter.clone() else {
            return Ok(fallback);
        };
        let key = crate::python_json::digest(&json!([question, context, instructions]));
        let (mut receiver, _waiter) = {
            let Ok(mut flights) = self.flights.lock() else {
                return Ok(fallback);
            };
            if !flights.contains_key(&key) {
                if flights.len() >= 8 {
                    return Ok(fallback);
                }
                let plan = Plan::new(question, context, instructions)?;
                let nonce = Uuid::new_v4();
                let (send, receiver) = watch::channel(None);
                let mut value = fallback.clone();
                let task = tokio::spawn(async move {
                    value.model_attempted = true;
                    match rewriter.rewrite(plan.permitted_payload()).await {
                        Ok(rewrite) => {
                            value.usage = rewrite.usage;
                            match plan.accept(&json!({"answer":rewrite.answer})) {
                                Ok(content) => {
                                    value.source = "ollama_generated_verified";
                                    value.content = Some(content);
                                }
                                Err(error) => value.error_code = Some(error.0),
                            }
                        }
                        Err(error) => {
                            value.error_code = Some(error.failure.0);
                            value.usage = error.usage;
                        }
                    }
                    send.send_replace(Some(Arc::new(value)));
                });
                let abort = task.abort_handle();
                drop(task);
                flights.insert(
                    key.clone(),
                    Entry {
                        nonce,
                        waiters: 0,
                        receiver,
                        abort,
                    },
                );
            }
            let entry = flights.get_mut(&key).expect("flight");
            entry.waiters += 1;
            (
                entry.receiver.clone(),
                Waiter {
                    flights: self.flights.clone(),
                    key: key.clone(),
                    nonce: entry.nonce,
                },
            )
        };
        loop {
            if let Some(value) = receiver.borrow_and_update().clone() {
                return Ok((*value).clone());
            }
            if receiver.changed().await.is_err() {
                let mut fallback = fallback;
                fallback.error_code = Some("local_rewriter_stopped");
                fallback.model_attempted = true;
                return Ok(fallback);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct State {
        calls: AtomicUsize,
        drops: AtomicUsize,
        entered: tokio::sync::Notify,
        release: tokio::sync::Semaphore,
        hold: bool,
        mode: &'static str,
    }
    struct Fake {
        state: Arc<State>,
    }
    struct Dropped(Arc<State>);
    impl Drop for Dropped {
        fn drop(&mut self) {
            self.0.drops.fetch_add(1, Ordering::SeqCst);
        }
    }
    impl Rewriter for Fake {
        fn rewrite(
            &self,
            payload: Value,
        ) -> Pin<Box<dyn Future<Output = std::result::Result<Rewrite, RewriteFailure>> + Send>>
        {
            let shared = self.state.clone();
            Box::pin(async move {
                let _drop = Dropped(shared.clone());
                shared.calls.fetch_add(1, Ordering::SeqCst);
                shared.entered.notify_one();
                if shared.hold {
                    shared.release.acquire().await.unwrap().forget();
                }
                let usage = Some(Usage {
                    input_tokens: Some(3),
                    output_tokens: Some(4),
                });
                if shared.mode == "failure" {
                    return Err(RewriteFailure {
                        failure: Failure("timeout"),
                        usage,
                    });
                }
                let mut sentences = payload["permitted_sentences"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|row| row[0].as_str().unwrap())
                    .collect::<Vec<_>>();
                sentences.reverse();
                Ok(Rewrite {
                    answer: if shared.mode == "unsafe" {
                        "I invented millions of users.".into()
                    } else {
                        sentences.join(" ")
                    },
                    usage,
                })
            })
        }
    }
    fn context() -> Value {
        json!({"evidence":[{"reference":{"source_type":"verified_project","source_id":"fictional:project:0"},"facts":{"contribution":"I built Rust workers. I tested the workers."}}]})
    }
    fn instructions() -> Value {
        json!({"max_characters":1000,"max_words":100,"style_instruction":"concise"})
    }
    fn options() -> Options {
        Options {
            rewrite: true,
            low_memory: false,
            route: Route::Narrative,
        }
    }
    fn make_engine(hold: bool, mode: &'static str) -> (Engine, Arc<State>) {
        let state = Arc::new(State {
            calls: AtomicUsize::new(0),
            drops: AtomicUsize::new(0),
            entered: Default::default(),
            release: tokio::sync::Semaphore::new(0),
            hold,
            mode,
        });
        (
            Engine::with_rewriter(Arc::new(Fake {
                state: state.clone(),
            })),
            state,
        )
    }
    async fn waiters(engine: &Engine, total: usize) {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while engine
                .flights
                .lock()
                .unwrap()
                .values()
                .map(|e| e.waiters)
                .sum::<usize>()
                != total
            {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    }
    fn spawn(engine: Engine, question: &str) -> tokio::task::JoinHandle<SafeAnswer> {
        let question = question.to_owned();
        tokio::spawn(async move {
            engine
                .answer(&question, &context(), &instructions(), options())
                .await
                .unwrap()
        })
    }
    #[tokio::test(flavor = "current_thread")]
    async fn versioned_deterministic_extraction_never_constructs_a_rewriter() {
        let value = Engine::default()
            .answer(
                "Describe my project",
                &context(),
                &instructions(),
                options(),
            )
            .await
            .unwrap();
        assert_eq!(value.source(), "deterministic_extractive");
        assert_eq!(value.status(), "draft_ready");
        assert!(!value.used_llm());
        assert!(!value.model_attempted());
        assert_eq!(value.contract_version, "local_answer.v1");
        assert_eq!(value.content().unwrap().claims.len(), 2);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn resolver_factual_summary_low_memory_and_single_clause_paths_never_dispatch() {
        let (engine, state) = make_engine(false, "valid");
        for route in [
            Route::FactualExtraction,
            Route::ApprovedSummary,
            Route::ProfileLink,
            Route::ResumeStatus,
        ] {
            let value = engine
                .answer(
                    "Describe my project",
                    &context(),
                    &instructions(),
                    Options { route, ..options() },
                )
                .await
                .unwrap();
            assert!(!value.model_attempted());
        }
        let value = engine
            .answer(
                "Describe my project",
                &context(),
                &instructions(),
                Options {
                    low_memory: true,
                    ..options()
                },
            )
            .await
            .unwrap();
        assert_eq!(value.source(), "deterministic_extractive");
        let mut one = context();
        one["evidence"][0]["facts"]["contribution"] = json!("I built Rust workers.");
        assert!(
            !engine
                .answer("Describe my project", &one, &instructions(), options())
                .await
                .unwrap()
                .model_attempted()
        );
        let value = engine
            .answer(
                "resume",
                &Value::Null,
                &Value::Null,
                Options {
                    route: Route::ResumeStatus,
                    ..options()
                },
            )
            .await
            .unwrap();
        assert_eq!(value.source(), "needs_input");
        assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn missing_facts_and_constraints_abstain_before_inference_without_citations() {
        let (engine, state) = make_engine(false, "valid");
        let value = engine
            .answer("How many users?", &context(), &instructions(), options())
            .await
            .unwrap();
        assert_eq!(value.source(), "needs_input");
        assert!(value.content().is_none());
        assert!(!value.missing_information.is_empty());
        let mut limits = instructions();
        limits["max_words"] = json!(1);
        let value = engine
            .answer("Describe my project", &context(), &limits, options())
            .await
            .unwrap();
        assert_eq!(value.source(), "validation_failed");
        assert!(value.content().is_none());
        assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    }
    #[tokio::test(flavor = "current_thread")]
    async fn successful_rewrite_and_failed_or_unpermitted_rewrite_keep_distinct_provenance() {
        for mode in ["valid", "unsafe", "failure"] {
            let (engine, state) = make_engine(false, mode);
            let value = engine
                .answer(
                    "Describe my project",
                    &context(),
                    &instructions(),
                    options(),
                )
                .await
                .unwrap();
            assert!(value.model_attempted());
            assert_eq!(state.calls.load(Ordering::SeqCst), 1);
            assert_eq!(value.usage.unwrap().output_tokens, Some(4));
            if mode == "valid" {
                assert!(value.used_llm());
                assert_eq!(value.source(), "ollama_generated_verified");
                assert_eq!(
                    value.content().unwrap().claims[0].quote,
                    "I tested the workers."
                );
            } else {
                assert!(!value.used_llm());
                assert_eq!(value.source(), "deterministic_extractive");
                assert!(value.error_code().is_some());
                assert!(!value.content().unwrap().answer.contains("millions"));
            }
            assert!(engine.flights.lock().unwrap().is_empty());
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn identical_overlapping_requests_share_one_transport_and_one_waiter_can_cancel() {
        let (engine, state) = make_engine(true, "valid");
        let first = spawn(engine.clone(), "Describe my project");
        state.entered.notified().await;
        let second = spawn(engine.clone(), "Describe my project");
        waiters(&engine, 2).await;
        first.abort();
        assert!(first.await.err().unwrap().is_cancelled());
        waiters(&engine, 1).await;
        assert_eq!(state.drops.load(Ordering::SeqCst), 0);
        state.release.add_permits(1);
        assert!(second.await.unwrap().used_llm());
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        assert!(engine.flights.lock().unwrap().is_empty());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn last_waiter_cancellation_aborts_transport_and_removes_only_its_flight() {
        let (engine, state) = make_engine(true, "valid");
        let task = spawn(engine.clone(), "Describe my project");
        state.entered.notified().await;
        task.abort();
        assert!(task.await.err().unwrap().is_cancelled());
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while state.drops.load(Ordering::SeqCst) == 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(engine.flights.lock().unwrap().is_empty());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn capacity_is_eight_and_completed_results_are_never_a_persistent_candidate_cache() {
        let (engine, state) = make_engine(true, "valid");
        let mut tasks = vec![];
        for n in 0..8 {
            tasks.push(spawn(engine.clone(), &format!("Describe my project {n}")));
        }
        waiters(&engine, 8).await;
        let fallback = engine
            .answer(
                "Describe my project ninth",
                &context(),
                &instructions(),
                options(),
            )
            .await
            .unwrap();
        assert!(!fallback.model_attempted());
        for task in tasks {
            task.abort();
            let _ = task.await;
        }
        assert!(engine.flights.lock().unwrap().is_empty());
        assert!(state.calls.load(Ordering::SeqCst) <= 8);
        let (engine, state) = make_engine(false, "valid");
        for _ in 0..2 {
            assert!(
                engine
                    .answer(
                        "Describe my project",
                        &context(),
                        &instructions(),
                        options()
                    )
                    .await
                    .unwrap()
                    .used_llm()
            );
        }
        assert_eq!(state.calls.load(Ordering::SeqCst), 2);
        assert!(engine.flights.lock().unwrap().is_empty());
    }
}
