"""Owner-operated recovery of one untouched first question, never an Apply retry.

Used only under STOP after a trusted extension inspection of the exact durable
original tab. No grants, answers, submission records or old evidence are reset.
"""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.browser import chrome_profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.execution import naukri_identity, store
from backend.app.execution.naukri_receipts import prevents_replay
from backend.app.execution.queue_contracts import NaukriQuestionnaire
from backend.app.services.applications.service import ApplicationPacketService


async def recover(session, identity, expected_revision, proof):
    await store.memory_row(session, lock=True)
    config = await queue.configuration(session)
    row = await queue.load(session, identity)
    value = dict(row.value)
    if (
        config["state"] != "STOPPED"
        or value["revision"] != expected_revision
        or value["stage"] != "PAUSED"
        or not value.get("form_pending")
        or value.get("lease_token")
        or value.get("questionnaire_answers")
        or value.get("questionnaire_steps", 0)
        or value.get("admitted_actions", []) != [
            a for a in value.get("admitted_actions", [])
            if a["fingerprint"] == "apply:initial"
        ]
        or len(value.get("admitted_actions", [])) != 1
        or value.get("paused_context", {}).get("reason")
        != "questionnaire_verified_answer_required"
        or await prevents_replay(session, value["requisition"])
    ):
        raise ToolDenied("untouched_first_question_under_stop_required")
    packet = await ApplicationPacketService(session).read(UUID(value["packet_id"]))
    if (packet.lifecycle_state != "submitting" or packet.revision != value["packet_revision"]
            or packet.candidate_profile_version != value["profile_version"] or packet.readiness.stale):
        raise ToolDenied("questionnaire_packet_context_changed")
    account = await naukri_identity.require(session, value["candidate_profile_id"])
    selected = await chrome_profiles.selection(session)
    profile = (await session.get(OwnerPreference, chrome_profiles.PROFILE + selected["profile_binding_id"])).value
    binding = proof["binding"]
    original = value["form_binding"]
    if (not chrome_profiles.online(profile) or not profile["commands_enabled"]
            or account["revision"] != value["account_binding_revision"]
            or account["account_sha256"] != value["account_sha256"]
            or binding != {"profile_binding_id": profile["id"],
                           "browser_session_id": profile["browser_session_id"],
                           "window_id": profile["window_id"], "tab_id": original["tab_id"]}
            or any(binding[k] != original[k] for k in ("profile_binding_id", "window_id", "tab_id"))):
        raise ToolDenied("retained_recovery_context_changed")
    now = await instant(session)
    observed = datetime.fromisoformat(proof["observed_at"])
    step = NaukriQuestionnaire.model_validate({k: v for k, v in proof["questionnaire"].items() if k != "kind"})
    if (not timedelta(0) <= now - observed <= timedelta(minutes=2)
            or proof["work_id"] != value["id"] or proof["url"] != value["url"]
            or proof["requisition"] != value["requisition"]
            or proof.get("empty_first_question") is not True
            or step.answer_kind != "text" or step.options
            or step.question != value["questionnaire"]["question"]):
        raise ToolDenied("untouched_original_question_observation_required")
    signature = hashlib.sha256(json.dumps([value["url"], step.question, step.answer_kind, step.options],
                                        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if signature != step.step_sha256:
        raise ToolDenied("questionnaire_step_evidence_changed")
    recovered = {**binding, "profile_version": profile["version"], "selection_version": selected["version"]}
    value["unanswered_session_recoveries"] = [*value.get("unanswered_session_recoveries", []), {
        "at": now.isoformat(), "old_form_binding": original,
        "old_questionnaire": value["questionnaire"], "new_form_binding": recovered,
        "new_questionnaire": step.model_dump(mode="json"),
        "source": "trusted_extension_exact_original_empty_first_question",
        "proof_sha256": hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest(),
    }]
    value.update(form_binding=recovered, questionnaire_document_id=step.document_id,
                 questionnaire=step.model_dump(mode="json"), revision=value["revision"] + 1,
                 updated_at=now.isoformat())
    value.pop("questionnaire_answer", None)
    row.value = value
    await queue.event(session, value, "untouched_first_question_session_recovered_no_apply")
    return value
