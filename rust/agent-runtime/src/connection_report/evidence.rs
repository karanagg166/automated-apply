use super::*;

pub(super) async fn browser(
    connection: &mut PgConnection,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<[Row; 2]> {
    let profile: Option<Value> = sqlx::query_scalar(
        "SELECT jsonb_build_object('last_heartbeat',p.value->'last_heartbeat','connected',p.value->'connected','window_id',p.value->'window_id')
         FROM owner_preferences s JOIN owner_preferences p ON p.key='chr_prof:'||(s.value->>'profile_binding_id')
         WHERE s.key='chr_selection' AND p.value->>'id'=s.value->>'profile_binding_id' AND p.value->>'owner'='primary'",
    ).fetch_optional(connection).await.map_err(db)?;
    let browser_name = match config.browser {
        crate::browser_inventory::Browser::Brave => "Brave extension",
        crate::browser_inventory::Browser::Edge => "Edge extension",
        crate::browser_inventory::Browser::Safari => "Safari extension",
    };
    let mut rows = [browser_name, "Native messaging host"].map(|name| {
        Row::new(
            name,
            "core",
            config.browser_profiles.native_enabled,
            "Review the selected browser profile and the local native host installation.",
        )
    });
    let available = config.browser_profiles.native_enabled
        && config.browser.native_manifest_directory().is_some();
    let connected = available
        && profile
            .as_ref()
            .is_some_and(|value| crate::browser_profiles::online(value, now).unwrap_or(false));
    for row in &mut rows {
        row.evidence(
            if connected {
                "authenticated"
            } else if config.browser_profiles.native_enabled {
                "owner_action_required"
            } else {
                "disabled"
            },
            if connected {
                "saved_selected_profile_heartbeat"
            } else {
                "configuration_inspection"
            },
            profile
                .as_ref()
                .and_then(|value| stored_time(&value["last_heartbeat"])),
        );
        row.identity_verification = if connected {
            "configured_extension_origin"
        } else {
            "unverified"
        };
        row.capability_verification = if connected {
            "bridge_heartbeat_only"
        } else {
            "unverified"
        };
        row.owner_authorization_required = !connected;
        row.blocker = (!connected).then_some(if available {
            "selected_profile_heartbeat_required"
        } else {
            "native_bridge_not_configured"
        });
        if available {
            row.capabilities = json!(["url_preview", "gesture_session_observation"]);
        }
    }
    Ok(rows)
}

pub(super) async fn telegram(
    connection: &mut PgConnection,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Row> {
    let mut row = Row::new(
        "Telegram worker",
        "core",
        config.telegram.is_some(),
        "Review the owner bot binding and check its private command response.",
    );
    let Some(settings) = config.telegram.as_ref() else {
        row.state = "disabled".into();
        return Ok(row);
    };
    row.capabilities = json!(["private_commands", "preview_only"]);
    let (state_table, outbox): (bool, bool) = sqlx::query_as(
        "SELECT to_regclass('agent_telegram_state') IS NOT NULL AND to_regclass('rust_telegram_runtime') IS NOT NULL,
         to_regclass('rust_telegram_outbox') IS NOT NULL AND to_regclass('agent_operations') IS NOT NULL",
    ).fetch_one(&mut *connection).await.map_err(db)?;
    let poll: Option<(Option<DateTime<Utc>>, bool)> = if state_table {
        sqlx::query_as("SELECT s.last_poll_at,s.last_error IS NOT NULL FROM agent_telegram_state s
             JOIN rust_telegram_runtime r USING(key) WHERE r.key='primary' AND r.binding=$1 AND s.bot_id=$2 AND s.evidence_type=$3")
            .bind(settings.binding()).bind(settings.bot_id()).bind(if config.fixture { "simulated_transport" } else { "live_poll" })
            .fetch_optional(&mut *connection).await.map_err(db)?
    } else {
        None
    };
    let time = poll.and_then(|(time, _)| time);
    let error = poll.is_some_and(|(_, error)| error);
    let fresh = time
        .is_some_and(|at| (0..90_000).contains(&now.signed_duration_since(at).num_milliseconds()));
    let mut roundtrip = false;
    if !config.fixture && !error && fresh && outbox {
        let updates: Vec<i64> = sqlx::query_scalar(
            "SELECT update_id FROM rust_telegram_outbox WHERE binding=$1
            AND state='sent' AND receipt_message_id IS NOT NULL AND update_id IS NOT NULL
            ORDER BY update_id DESC LIMIT 10",
        )
        .bind(settings.binding())
        .fetch_all(&mut *connection)
        .await
        .map_err(db)?;
        let keys: Vec<_> = updates
            .into_iter()
            .map(|update| settings.operation_key(update))
            .collect();
        roundtrip = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM agent_operations WHERE key=ANY($1) AND result->'ok'='true'::jsonb)")
            .bind(keys).fetch_one(connection).await.map_err(db)?;
    }
    let (state, evidence) = if config.fixture && poll.is_some() {
        ("degraded", "simulated_transport")
    } else if error {
        ("degraded", "saved_poll_error")
    } else if roundtrip {
        (
            "capability_verified",
            "bound_poll_receipt_and_dispatch_audit",
        )
    } else if fresh {
        ("authenticated", "recent_bound_poll")
    } else {
        ("disconnected", "configured_binding_no_recent_poll")
    };
    row.evidence(state, evidence, time);
    if fresh && !config.fixture {
        row.identity_verification = "configured_bot_binding_matched";
    }
    row.capability_verification = if roundtrip {
        "owner_command_roundtrip"
    } else if fresh && !config.fixture {
        "poll_only"
    } else {
        "unverified"
    };
    row.latest_error_category = error.then_some("telegram_poll_error");
    row.blocker = if state_table {
        (!fresh).then_some("recent_owner_bot_poll_required")
    } else {
        Some("telegram_runtime_schema_required")
    };
    row.owner_authorization_required = !fresh;
    Ok(row)
}

pub(super) async fn candidate(
    connection: &mut PgConnection,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<[Row; 2]> {
    let saved: Option<(bool, bool, Option<String>)> = sqlx::query_as(
        "SELECT (p.verified_experience_years BETWEEN 0 AND 100 AND
         jsonb_typeof(p.verified_skills::jsonb)='array' AND p.verified_skills::jsonb<>'[]' AND
         jsonb_typeof(p.preferences::jsonb->'target_titles')='array' AND p.preferences::jsonb->'target_titles'<>'[]' AND
         jsonb_typeof(p.preferences::jsonb->'preferred_locations')='array' AND p.preferences::jsonb->'preferred_locations'<>'[]') IS TRUE,
         (c.value->>'profile_id'=p.id::text AND c.value->'profile_version'=to_jsonb(p.version)) IS TRUE,
         CASE WHEN length(c.value->>'confirmed_at')<=40 THEN c.value->>'confirmed_at' END
         FROM candidate_profiles p LEFT JOIN owner_preferences c ON c.key='phase1_profile_confirmation' WHERE p.singleton_key='primary'",
    ).fetch_optional(&mut *connection).await.map_err(db)?;
    let time = saved
        .as_ref()
        .and_then(|(_, confirmed, stamp)| {
            if !*confirmed {
                return None;
            }
            DateTime::parse_from_rfc3339(stamp.as_deref()?)
                .ok()
                .map(|value| value.to_utc())
        })
        .filter(|at| *at <= now);
    let ready = time.is_some() && saved.as_ref().is_some_and(|(required, _, _)| *required);
    let mut profile = Row::new(
        "Candidate profile",
        "core",
        saved.is_some(),
        "Review the required facts and confirm the current profile version.",
    );
    profile.evidence(
        if ready {
            "capability_verified"
        } else {
            "owner_action_required"
        },
        if time.is_some() {
            "version_bound_owner_confirmation"
        } else {
            "current_sql_inventory_no_personal_details"
        },
        time,
    );
    profile.identity_verification = if time.is_some() {
        "owner_confirmed_current_version"
    } else {
        "unverified"
    };
    profile.capability_verification = if ready {
        "reviewed_required_profile_fields_present"
    } else {
        "profile_review_or_required_fields_missing"
    };
    if saved.is_some() {
        profile.capabilities = json!(["saved_canonical_profile"]);
    }
    profile.owner_authorization_required = !ready;
    profile.blocker = (!ready).then_some("owner_fact_review_pending");

    let deps: bool = sqlx::query_scalar("SELECT to_regclass('private_resumes') IS NOT NULL AND to_regclass('candidate_resources') IS NOT NULL")
        .fetch_one(&mut *connection).await.map_err(db)?;
    let mut pdfs: Vec<(Option<Vec<u8>>, String)> = if deps {
        sqlx::query_as("SELECT CASE WHEN octet_length(f.ciphertext)<=7340032
            AND r.source_type='private_upload' AND r.url='private-resume:'||f.id::text THEN f.ciphertext END, f.sha256
            FROM private_resumes f JOIN candidate_resources r ON r.id=f.resource_id
            JOIN candidate_profiles p ON p.id=r.candidate_profile_id
            WHERE p.singleton_key='primary' AND f.confirmed AND r.user_confirmed AND r.is_primary AND r.resource_type='resume'
            ORDER BY f.id LIMIT 2").fetch_all(connection).await.map_err(db)?
    } else {
        vec![]
    };
    let selected = !pdfs.is_empty();
    let integrity = pdfs.len() == 1
        && pdfs.pop().is_some_and(|(ciphertext, digest)| {
            ciphertext.is_some_and(|bytes| config.resumes.verified(&bytes, &digest).is_ok())
        });
    let mut resume = Row::new(
        "Resume",
        "core",
        selected,
        "Review and confirm the canonical private PDF.",
    );
    resume.evidence(
        if integrity {
            "capability_verified"
        } else if selected {
            "degraded"
        } else {
            "owner_action_required"
        },
        if integrity {
            "current_encrypted_file_integrity_check"
        } else {
            "current_sql_inventory_no_personal_details"
        },
        integrity.then_some(now),
    );
    if integrity {
        resume.identity_verification = "owner_confirmed_canonical_file";
        resume.capability_verification = "decrypted_pdf_hash_verified";
        resume.capabilities = json!(["private_canonical_resume"]);
    }
    resume.owner_authorization_required = !integrity;
    resume.blocker = if integrity {
        None
    } else if !deps {
        Some("private_resume_schema_required")
    } else if selected {
        Some("canonical_resume_integrity_or_selection_failed")
    } else {
        Some("canonical_resume_confirmation_pending")
    };
    Ok([profile, resume])
}

pub(super) async fn gmail(
    connection: &mut PgConnection,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Vec<Row>> {
    let oauth = config.mailboxes.provider().is_ok();
    let legacy = crate::gmail_legacy::status_in(connection, &config.gmail_accounts, oauth).await?;
    let bound_email = legacy["account_email"].as_str().is_some_and(|email| {
        !email.is_empty()
            && config
                .gmail_accounts
                .legacy_expected_email
                .as_deref()
                .is_some_and(|expected| {
                    automated_apply_domain::text::folded(email)
                        == automated_apply_domain::text::folded(expected)
                })
    });
    let time = stored_time(&legacy["last_verified_at"]).filter(|at| {
        *at <= now
            && bound_email
            && legacy["verification_recorded"] == true
            && legacy["account_authorized"] == true
            && legacy["google_subject"]
                .as_str()
                .is_some_and(|subject| !subject.is_empty())
    });
    let mut rows = Vec::new();
    for (name, bound) in [
        ("Gmail identity", time.is_some()),
        (
            "Gmail compose",
            time.is_some() && legacy["authorization_state"] == "compose_authorized",
        ),
    ] {
        let mut row = Row::new(
            name,
            "ai",
            oauth,
            "Review the Gmail consent and authorized account. Draft creation has a separate permission check.",
        );
        row.evidence(
            if bound {
                "authenticated"
            } else {
                "owner_authorization_required"
            },
            if bound {
                "saved_oauth_evidence"
            } else {
                "configuration_inspection"
            },
            time.filter(|_| bound),
        );
        row.owner_authorization_required = !bound;
        if bound {
            row.identity_verification = "saved_oauth_bound_expected_account";
            row.capability_verification = "saved_oauth_grant_only";
            row.capabilities = if name == "Gmail compose" {
                json!(["draft_scope_granted_sending_disabled"])
            } else {
                json!(["saved_secondary_identity"])
            };
        } else {
            row.blocker = Some("gmail_account_consent_required");
        }
        rows.push(row);
    }
    for slot in 1..=config.mailboxes.configured_slots() {
        let proof =
            crate::mailboxes::connection_evidence(connection, slot, &config.mailboxes).await?;
        let mut row = Row::new(
            format!("Gmail slot {slot}"),
            "ai",
            oauth,
            "Review the saved mailbox permissions before reading mail or preparing drafts.",
        );
        let time = proof
            .and_then(|proof| stored_time(&proof))
            .filter(|at| *at <= now);
        row.evidence(
            if time.is_some() {
                "authenticated"
            } else {
                "owner_authorization_required"
            },
            if time.is_some() {
                "saved_oauth_evidence"
            } else {
                "configuration_inspection"
            },
            time,
        );
        row.owner_authorization_required = time.is_none();
        if time.is_some() {
            row.identity_verification = "saved_oauth_allowlist_match";
            row.capability_verification = "saved_read_and_draft_grant_only";
            row.capabilities = json!(["read_mail", "create_draft_if_enabled"]);
        }
        rows.push(row);
    }
    Ok(rows)
}
