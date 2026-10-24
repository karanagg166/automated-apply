"""Actual host/API/PostgreSQL restart lifecycle; Chrome/Telegram events are simulated."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--with-chromium-extension", action="store_true")
    args = parser.parse_args()
    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings
    original = Path(args.env_file).resolve()
    settings = load_settings(str(original))
    from sqlalchemy.engine import make_url
    target = make_url(settings.DATABASE_URL)
    if target.host != "127.0.0.1" or target.database != "candidate_profile_test":
        raise SystemExit("disposable_localhost_database_required")
    private = ROOT / "reports/phase1/lifecycle.private.env"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(original.read_text().replace(settings.LOCAL_AGENT_ENDPOINT, "http://127.0.0.1:18082"))
    if args.with_chromium_extension:
        import hashlib
        digest = hashlib.sha256(str((ROOT / "extension").resolve()).encode()).hexdigest()[:32]
        identity = "".join(chr(ord('a') + int(char, 16)) for char in digest)
        lines = [line for line in private.read_text().splitlines() if not line.startswith("CHROME_EXTENSION_ID=")]
        private.write_text("\n".join(lines) + "\nCHROME_EXTENSION_ID=" + identity + "\n")
    private.chmod(0o600)
    settings = load_settings(str(private))
    configure_operator(settings)
    endpoint = settings.LOCAL_AGENT_ENDPOINT
    headers = {"Authorization": "Bearer " + settings.JOB_AGENT_API_TOKEN.get_secret_value()}
    log = (ROOT / "reports/phase1/lifecycle-api.log").open("w")
    process = None
    def start():
        child = subprocess.Popen([sys.executable, "backend/scripts/phase1/local_service.py", "api", "--env-file", str(private)], cwd=ROOT, stdout=log, stderr=log)
        for _ in range(60):
            if child.poll() is not None:
                raise RuntimeError("lifecycle_backend_start_failed")
            try:
                if httpx.get(endpoint + "/ready", timeout=1, trust_env=False).status_code == 200:
                    return child
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        child.terminate()
        raise RuntimeError("lifecycle_backend_timeout")
    try:
        process = start()
        extension = subprocess.run(["node", "extension/tests/bridge-e2e.mjs", sys.executable, str(private), settings.CHROME_EXTENSION_ID], cwd=ROOT, capture_output=True, text=True, timeout=35, check=True)
        result = json.loads(extension.stdout)
        assert result["ok"] and not result["data"]["submitted"]
        request_id = result["request_id"]
        if args.with_chromium_extension:
            browser = subprocess.run(["node", "frontend/scripts/verify-extension-native.mjs", sys.executable,
                str(private), settings.CHROME_EXTENSION_ID], cwd=ROOT, capture_output=True, text=True, timeout=90)
            if browser.returncode:
                # This probe contains fictional data only; retain useful assertion diagnostics.
                raise AssertionError("isolated_extension_probe_failed:\n" + browser.stderr[-4000:])
            assert json.loads(browser.stdout)["state"] == "passed"
        preferences = {"target_titles": ["Fictional Backend Engineer"], "minimum_employees": 2, "maximum_employees": 10}
        assert httpx.put(endpoint + "/api/v1/local-agent/search-preferences", headers=headers,
            json=preferences, timeout=10, trust_env=False).status_code == 200
        asyncio.run(telegram_test(settings))
        process.terminate()
        process.wait(timeout=15)
        process = start()
        history = httpx.get(endpoint + "/api/v1/local-agent/history", headers=headers, timeout=10, trust_env=False).json()
        assert any(row["result"]["request_id"] == request_id for row in history)
        saved = httpx.get(endpoint + "/api/v1/local-agent/search-preferences", headers=headers, timeout=10, trust_env=False).json()
        assert all(saved[key] == value for key, value in preferences.items())
        report = {"state": "passed", "database": "actual_disposable_postgresql17_public_restricted_role",
            "native_host": "actual_python_framing_open_stdin", "fastapi": "actual_loopback_http",
            "chrome_context_menu": "simulated_extension_api_events", "real_chrome_installation": "separate_owner_test",
            "telegram": "simulated_transport_actual_dispatcher_and_postgresql",
            "restart_persistence": True, "application_submitted": False, "email_sent": False}
        if args.with_chromium_extension:
            report["isolated_chromium_mv3_native_api"] = "actual_verified"
        (ROOT / "reports/phase1/lifecycle.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        log.close()


async def telegram_test(settings):
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.local_agent.models import TelegramDelivery, TelegramState
    from backend.app.local_agent.telegram import (
        TelegramError,
        reply_for,
        run_worker,
        worker_lock,
    )
    config = settings.model_copy(update={"TELEGRAM_OWNER_USER_ID": 424242, "TELEGRAM_OWNER_CHAT_ID": 424242})
    factory = get_session_factory()
    async with factory() as session:
        state = await session.get(TelegramState, "primary")
        next_id = state.next_update_id if state else 1
    stop = asyncio.Event()
    class FakeBot:
        async def verify(self):
            return {"id": 999999, "is_bot": True, "username": "fictional_phase1_bot"}
        async def call(self, method, payload):
            if method == "getUpdates":
                return [{"update_id": next_id, "message": {"chat": {"id": 424242, "type": "private"}, "from": {"id": 424242}, "text": "/apply https://example.org/jobs/fictional-telegram"}}]
            assert method == "sendMessage" and payload["chat_id"] == 424242
            assert "No application submitted" in payload["text"]
            stop.set()
            return {"message_id": 1}
    try:
        async with worker_lock(config):
            async with factory() as session:
                status = await asyncio.wait_for(reply_for(session, config,
                    {"text": "/status"}, next_id + 100, "fictional_phase1_bot"), timeout=20)
                assert "Supabase PostgreSQL" in status and "Local FastAPI" in status
                await session.commit()
            try:
                async with worker_lock(config):
                    raise AssertionError("duplicate_worker_lock_accepted")
            except TelegramError as exc:
                assert exc.code == "telegram_worker_already_running"
            await asyncio.wait_for(run_worker(config, factory, api=FakeBot(), stop=stop), timeout=20)
        async with factory() as session:
            delivery = await session.get(TelegramDelivery, next_id)
            assert delivery.state == "sent"
            assert (await session.get(TelegramState, "primary")).next_update_id == next_id + 1
    finally:
        await close_db_engine()


if __name__ == "__main__":
    main()
