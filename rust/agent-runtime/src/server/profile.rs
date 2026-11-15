//! Profile, evidence and factual-question request dispatch.
use super::{OwnerReply, evidence_id, missing_item};
use crate::{Failure, Result, configuration::Configuration};
use axum::http::StatusCode;
use sqlx::PgConnection;

pub(super) async fn missing_dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    body: &[u8],
    page: (i64, i64),
    proof: Option<crate::owner_proof::Proof>,
) -> Result<OwnerReply> {
    use crate::{missing_contract as contract, missing_store as store};
    let input =
        || serde_json::from_slice(body).map_err(|_| Failure("invalid_missing_input_request"));
    let data = if let Some((id, action)) = missing_item(path) {
        match (method, action) {
            ("GET", "") => store::read(connection, id).await,
            ("PATCH", "") => store::edit(connection, id, contract::normalize_edit(input()?)?).await,
            ("POST", "approve") => {
                store::approve(
                    connection,
                    id,
                    contract::normalize_approve(input()?)?,
                    proof.ok_or(Failure("owner_approval_required"))?,
                )
                .await
            }
            ("GET", "history") => store::history(connection, id, page.0, page.1).await,
            (_, "approve") => Err(Failure("match_method_not_allowed")),
            (_, "history") => Err(Failure("resource_read_method_not_allowed")),
            _ => Err(Failure("missing_item_method_not_allowed")),
        }
    } else {
        match method {
            "GET" => store::list(connection, page.0, page.1).await,
            "POST" => store::create(connection, contract::normalize_create(input()?)?).await,
            _ => Err(Failure("resource_list_method_not_allowed")),
        }
    }?;
    Ok(OwnerReply {
        data,
        status: if method == "POST" && missing_item(path).is_none() {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: None,
    })
}
pub(super) async fn candidate_resource_dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    body: &[u8],
    page: (i64, i64),
    config: &Configuration,
) -> Result<OwnerReply> {
    let result = match (method, path) {
        ("POST", "/api/v1/candidate/resources/resolve") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::resolve_question(connection, input, &config.resource_defaults)
                .await
        }
        (_, "/api/v1/candidate/resources/resolve") => Err(Failure("match_method_not_allowed")),
        ("GET", "/api/v1/candidate/resources" | "/api/v1/candidate/evidence") => {
            crate::resource_store::list(
                connection,
                path.ends_with("evidence"),
                page.0,
                page.1,
                &config.resource_defaults,
            )
            .await
        }
        ("POST", "/api/v1/candidate/resources") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_resource(connection, input, config.profile_live).await
        }
        ("POST", "/api/v1/candidate/evidence") => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_evidence(connection, None, input).await
        }
        ("PATCH", _) if evidence_id(path).is_some() => {
            let id = evidence_id(path)
                .unwrap()
                .parse()
                .map_err(|_| Failure("invalid_resource_selection"))?;
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_resource_input"))?;
            crate::resource_store::save_evidence(connection, Some(id), input).await
        }
        (_, "/api/v1/candidate/resources" | "/api/v1/candidate/evidence") => {
            Err(Failure("resource_list_method_not_allowed"))
        }
        _ => Err(Failure("evidence_patch_method_not_allowed")),
    }?;
    Ok(OwnerReply {
        data: result,
        status: if method == "POST" && path == "/api/v1/candidate/evidence" {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: None,
    })
}
pub(super) async fn profile_dispatch(
    connection: &mut PgConnection,
    method: &str,
    body: &[u8],
    if_match: Option<&str>,
    live: bool,
) -> Result<OwnerReply> {
    let saved = match method {
        "GET" => crate::profile_store::get(connection).await?,
        "PUT" | "PATCH" => {
            let input =
                serde_json::from_slice(body).map_err(|_| Failure("invalid_profile_input"))?;
            // The legacy HTTP contract validates the DTO before precondition headers.
            let supplied = crate::profile_contract::normalize(
                if method == "PATCH" {
                    crate::profile_contract::Operation::Update
                } else {
                    crate::profile_contract::Operation::Create
                },
                input,
            )?;
            let expected = crate::profile_contract::parse_version(if_match, method == "PATCH")?;
            crate::profile_store::save_normalized(
                connection,
                supplied,
                expected,
                method == "PATCH",
                live,
            )
            .await?
        }
        _ => return Err(Failure("profile_method_not_allowed")),
    };
    Ok(OwnerReply {
        data: saved.value,
        status: if saved.created {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        etag: Some(format!("\"{}\"", saved.version)),
    })
}
