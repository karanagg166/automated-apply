"""Actual review DTO and transactional notice function against fictional preloaded dependencies."""
import argparse
import ast
import asyncio
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as S
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict

from rust.scripts.packet_contract_corpus import packet_models

ROOT = Path(__file__).resolve().parents[2]


async def notices(scope):
    now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(_zone): return now

    scope.update(datetime=Clock, timezone=timezone, hashlib=hashlib, ConfigDict=ConfigDict, ZoneInfo=ZoneInfo, ZoneInfoNotFoundError=ZoneInfoNotFoundError)
    def load(path, name):
        node = next(n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        return node
    pref = load("backend/app/dashboard/schemas.py", "NotificationPreferences")
    ready = load("backend/app/services/applications/eligibility.py", "readiness")
    exec(compile(ast.Module(body=[pref, ready], type_ignores=[]), "isolated_notification_definitions", "exec"), scope)
    method = load("backend/app/execution/notifications.py", "notify_packet")

    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module not in {"backend.app.execution", "backend.app.dashboard.notifications", "backend.app.services.applications.eligibility", "backend.app.core.config", "backend.app.local_agent.models"}:
                raise ValueError("unexpected_notice_oracle_import")
            return None

    method = Imports().visit(method)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "backend/app/execution/notifications.py", "exec"), scope)
    classes = {name: type(name, (), {"id": "id", "dedup_key": "dedup_key", "update_id":"update_id"}) for name in ["Notification", "NotificationDelivery", "TelegramDelivery", "OwnerPreference"]}

    class Query:
        def __init__(self, model): self.model, self.data = model.__name__, None
        def values(self, **values): self.data = values; return self
        def on_conflict_do_nothing(self, **_kwargs): return self
        def returning(self, *_args): return self

    scope.update(classes)
    scope.update(insert_for=lambda _session: Query, store=S(TERMINAL={"REJECTED", "FAILED_FINAL", "SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN"}), TERMINAL={"user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown", "withdrawn", "abandoned"})
    snapshot = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-context-corpus.json").read_text())["outputs"][0]
    field = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-read-corpus.json").read_text())["fields"][0]
    field.update(effective_answer="Verified fact", proposed_answer="Verified fact", review_status="reviewed")
    base = dict(id="20000000-0000-0000-0000-000000000001", job_id="30000000-0000-0000-0000-000000000001", candidate_profile_id="10000000-0000-0000-0000-000000000001", candidate_profile_version=4, platform="naukri", snapshot=snapshot, fields=[field], readiness=dict(state="needs_review"), lifecycle_state="reviewed", tracking_state="not_applied", revision=2, approved_revision=None, review_status="reviewed", created_at=now.isoformat(), updated_at=now.isoformat())
    baseline = dict(packet=base, execution=dict(id="40000000-0000-0000-0000-000000000001", platform="naukri", state="READY_FOR_REVIEW", cancelled=False, automation_revision=3), automation=dict(revision=3, state="RUNNING", policy=dict(telegram_questions=True)), configuration=dict(mode="ON_DEMAND"), preferences={}, telegram_available=True)
    records = [baseline]
    for key, values in dict(platform=["wellfound"], lifecycle_state=["created", "abandoned", "withdrawn", "submitting", "submission_unknown", "provider_confirmed_submitted", "user_reported_submitted"], readiness=[dict(state="needs_review", stale=True), dict(state="needs_input"), dict(state="ready_for_manual_handoff")], approved_revision=[1, 2]).items():
        for value in values: records.append({**deepcopy(baseline), "packet": {**deepcopy(base), key: value}})
    manual = deepcopy(baseline); manual["packet"].update(approved_revision=2, lifecycle_state="approved_for_manual_handoff", readiness=dict(state="ready_for_manual_handoff")); records.append(manual)
    for key, value in [("destination", {**snapshot["destination"], "valid": False}), ("candidate", None), ("resume", {**snapshot["resume"], "selected": None})]:
        row = deepcopy(baseline); row["packet"]["snapshot"][key] = value; records.append(row)
    for changes in [dict(effective_answer=None, proposed_answer=None), dict(review_status="pending"), dict(provenance={**field["provenance"], "answer_expires_at": now.isoformat()})]:
        row = deepcopy(baseline); row["packet"]["fields"] = [{**field, **changes}]; records.append(row)
    executions = [None, {**baseline["execution"], "cancelled": True}, {**baseline["execution"], "platform": "wellfound"}, {**baseline["execution"], "automation_revision": 2}, *[{**baseline["execution"], "state": state} for state in ["REJECTED", "FAILED_FINAL", "SUBMITTED_CONFIRMED", "SUBMISSION_UNKNOWN", "PAUSED"]]]
    records.extend({**deepcopy(baseline), "execution": value} for value in executions)
    automations = [None, dict(revision=0, state="STOPPED"), dict(revision=3, state="STOPPED"), dict(revision=3, state="PAUSED"), dict(revision=3, state="RUNNING", policy=None), dict(revision=3, state="RUNNING", policy=dict(telegram_questions=False))]
    records.extend({**deepcopy(baseline), "automation": value} for value in automations)
    records.extend({**deepcopy(baseline), "configuration": value} for value in [None, {}, dict(mode="OFF"), dict(mode="WATCH_AND_NOTIFY"), dict(mode="AUTO_APPLY_WHEN_AUTHORIZED")])
    records.extend({**deepcopy(baseline), "preferences": value} for value in [dict(paused=True), dict(in_app=False), dict(paused=True, in_app=False)])
    records.append({**deepcopy(baseline), "telegram_available": False})
    outputs = []
    for raw in records:
        packet = scope["PacketRead"].model_validate(raw["packet"])
        prefs = scope["NotificationPreferences"].model_validate(raw["preferences"])

        class Session:
            def __init__(self): self.rows = []
            async def get(self, _model, key, **_kwargs):
                value = raw["automation"] if key == "naukri_automation" else raw["configuration"]
                return S(value=value) if value is not None else None
            async def execute(self, statement):
                self.rows.append(statement)
                return S(scalar_one_or_none=lambda: UUID(int=42))

        async def preferences(_session): return prefs
        scope["preferences"] = preferences
        scope["get_settings"] = lambda: S(TELEGRAM_BOT_TOKEN="fictional" if raw["telegram_available"] else None, TELEGRAM_OWNER_CHAT_ID=1, TELEGRAM_OWNER_USER_ID=2)
        session = Session()
        result = await scope["notify_packet"](session, S(value=raw["execution"]) if raw["execution"] is not None else None, packet)
        notice = next((r.data for r in session.rows if r.model == "Notification"), None)
        telegram = next((r.data for r in session.rows if r.model == "TelegramDelivery"), None)
        raw["packet"] = packet.model_dump(mode="json")
        raw["preferences"] = prefs.model_dump(mode="json")
        outputs.append(dict(input=raw, output=dict(notification=notice, telegram=telegram) if result else None))
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules: raise ValueError("notice_oracle_loaded_runtime")
    return dict(now=now.isoformat(), cases=outputs)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--check", action="store_true"); check = parser.parse_args().check
    scope = packet_models(); model = scope["ReviewInput"]
    base = dict(expected_revision=1)
    inputs = [base]
    for key, values in dict(expected_revision=[None, True, False, 0, "1.0", 1.5, 2147483646, 2147483647], action=[None, "review", "approve", " approve ", "submit"], reviewed_field_ids=[None, [], ["bad"], ["{10000000000000000000000000000001}"], ["10000000-0000-0000-0000-000000000001"] * 100, ["10000000-0000-0000-0000-000000000001"] * 101], confirm_resume=[None, True, 1, "yes", " true "], confirm_destination=[None, True, 0, "false"], approved_revision=[1], snapshot=[{}], submission_permission=[True]).items():
        inputs.extend({**base, key: value} for value in values)
    contracts = []
    for raw in inputs:
        try: result = dict(accepted=True, output=model.model_validate(raw).model_dump(mode="json"))
        except ValueError: result = dict(accepted=False)
        contracts.append(dict(input=raw, **result))
    data = dict(contracts=contracts, notices=asyncio.run(notices(scope)))
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-review-corpus.json"; encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded: raise SystemExit("packet_review_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_review_requests:{len(contracts)} actual_notice_cases:{len(data['notices']['cases'])}")


if __name__ == "__main__": main()
