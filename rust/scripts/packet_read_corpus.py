"""Execute actual packet service read/readiness against fictional preloaded repository records."""
import argparse
import ast
import asyncio
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as S
from uuid import UUID

from rust.scripts.packet_contract_corpus import packet_models

ROOT = Path(__file__).resolve().parents[2]


def load_method(scope, path, cls, name):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    method = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, "exec"), scope)
    return scope[name]


async def corpus():
    scope = packet_models()
    now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(_zone):
            return now

    eligibility = "backend/app/services/applications/eligibility.py"
    method = next(n for n in ast.parse((ROOT / eligibility).read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "readiness")
    scope.update(datetime=Clock, timezone=timezone)
    exec(compile(ast.Module(body=[method], type_ignores=[]), eligibility, "exec"), scope)
    project_field = load_method(scope, "backend/app/repositories/application_packet.py", "ApplicationPacketRepository", "field_read")
    read = load_method(scope, "backend/app/services/applications/service.py", "ApplicationPacketService", "read")
    snapshot = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-context-corpus.json").read_text())["outputs"][0]
    field = json.loads((ROOT / "rust/agent-runtime/tests/fixtures/packet-fields-corpus.json").read_text())["outputs"][0]["field"]
    field.update(id="10000000-0000-0000-0000-000000000001", proposed_answer=" Verified fact ", validation_status="draft_ready", review_status="reviewed")
    variants = [field, {**field, "review_status": "pending"}, {**field, "human_answer": ""}, {**field, "proposed_answer": None}, {**field, "validation_status": "file_upload_required"}]
    for expiry in ["2026-11-15T11:59:59.999999Z", "2026-11-15T12:00:00Z", "2026-11-15T12:00:00.000001Z"]:
        expired = deepcopy(field)
        expired["provenance"]["answer_expires_at"] = expiry
        variants.append(expired)
    lifecycles = scope["Lifecycle"].__args__
    cases = []
    for state in lifecycles:
        for flags in range(8):
            for i, row in enumerate(variants):
                stale, approved, submitted = [bool(flags & (1 << bit)) for bit in range(3)]
                owner = UUID("20000000-0000-0000-0000-000000000001")
                packet = S(id=owner, job_id=owner, candidate_profile_id=owner, candidate_profile_version=4, platform="naukri", snapshot=deepcopy(snapshot), resume_resource_id=None, lifecycle_state=state, tracking_state="not_applied", revision=1, approved_revision=1 if approved else None, created_at=now, updated_at=now)

                class Repo:
                    async def get(self, *_args, **_kwargs): return packet
                    async def fields(self, *_args): return [S(**row)]
                    async def submission(self, *_args): return object() if submitted else None
                    field_read = staticmethod(project_field)

                class Builder:
                    async def context(self, *_args, **_kwargs):
                        current = scope["PacketSnapshot"].model_validate(snapshot)
                        if stale: current.context_digest = "b" * 64
                        return None, S(id=owner), current

                result = await read(S(repo=Repo(), builder=Builder()), owner)
                cases.append(dict(lifecycle=state, flags=flags, field=i, readiness=result.readiness.model_dump(mode="json"), review_status=result.review_status))
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("packet_read_oracle_loaded_runtime")
    return dict(now=now.isoformat(), snapshot=snapshot, fields=variants, cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    data = asyncio.run(corpus())
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-read-corpus.json"
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded: raise SystemExit("packet_read_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_packet_service_read_states:{len(data['cases'])}")


if __name__ == "__main__":
    main()
