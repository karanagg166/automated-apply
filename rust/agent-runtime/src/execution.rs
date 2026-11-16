//! Legacy application execution parity. Pure policy/observations confer no browser authority.
pub mod contracts;
pub mod filters;
pub mod queue_page;
mod queue_status;
pub mod receipts;
mod storage;

use crate::{Failure, Result};
use serde_json::Value;
use sqlx::{Connection, PgConnection};
#[derive(Clone, Copy)]
pub enum Route {
    Queue,
    Account,
}
impl Route {
    pub fn method(self) -> &'static str {
        "GET"
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/execution/queue" => Some(Route::Queue),
        "/api/v1/execution/naukri/account-binding" => Some(Route::Account),
        _ => None,
    }
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("execution_method_not_allowed"));
    }
    let page = if matches!(route, Route::Queue) {
        Some(queue_page::Page::parse(query)?)
    } else {
        if query.is_some() {
            return Err(Failure("invalid_execution_page"));
        }
        None
    };
    let mut tx = c.begin().await.map_err(storage::db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(storage::db)?;
    let result = match route {
        Route::Queue => queue_status::listing(&mut tx, page.unwrap()).await,
        Route::Account => queue_status::account(&mut tx).await,
    };
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_read_commit_failed"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
