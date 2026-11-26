"""Free LLM fallback router: skip unconfigured, fail over on 429/503/timeout/bad JSON,
circuit breaker, persisted minute/day quotas, clean exhaustion, wire formats."""

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel

from backend.app.ai_v2.providers import (
    PROVIDER_REGISTRY,
    build_request,
    parse_response,
    resolve_provider,
)
from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter
from backend.app.ai_v2.usage import MemoryUsageStore, PostgresUsageStore
from backend.scripts.migrate_v2_core import MIGRATION, strip_pgvector
from backend.tests.test_browser_v2_postgres_store import BOOTSTRAP
from backend.tests.test_v2_migration_sql import PG_BIN, free_port

FAKE = "TEST_FAKE_TOKEN_ONLY"
ALL_KEYS = {"GROQ_API_KEY": FAKE, "GEMINI_API_KEY": FAKE, "MISTRAL_API_KEY": FAKE, "OPENROUTER_API_KEY": FAKE,
            "CLOUDFLARE_API_TOKEN": FAKE, "CLOUDFLARE_ACCOUNT_ID": "acct-test", "GITHUB_MODELS_TOKEN": FAKE}
WITH_CEREBRAS = ALL_KEYS | {"CEREBRAS_API_KEY": FAKE}  # Phase 6A provider (kept out of the failover fixtures)
HOSTS = {"api.groq.com": "groq", "generativelanguage.googleapis.com": "gemini", "api.mistral.ai": "mistral",
         "openrouter.ai": "openrouter", "api.cloudflare.com": "cloudflare", "models.github.ai": "github_models",
         "api.cerebras.ai": "cerebras"}


class Answer(BaseModel):
    answer: str
    confidence: float


GOOD = {"answer": "Yes", "confidence": 0.9}


def ok_body(provider, payload=GOOD):
    text = json.dumps(payload)
    if provider == "gemini":
        return {"candidates": [{"content": {"parts": [{"text": text}]}}],
                "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 7}}
    if provider == "cloudflare":
        return {"success": True, "result": {"response": text, "usage": {"prompt_tokens": 40,
                                                                          "completion_tokens": 6}}}
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 30, "completion_tokens": 5}}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 26, 10, 0, 30, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def make_router(behaviour, env=None, usage=None, clock=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider = HOSTS[request.url.host]
        calls.append(provider)
        action = behaviour.get(provider, "ok")
        if callable(action):
            action = action(len([c for c in calls if c == provider]))
        if action == "ok":
            return httpx.Response(200, json=ok_body(provider))
        if action == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if action == "bad_json":
            return httpx.Response(200, json=ok_body(provider, {"oops": True}))
        if action == "prose":
            return httpx.Response(200, json={"choices": [{"message": {"content": "Sure! I think yes."}}]})
        if isinstance(action, tuple):
            status, headers = action
            return httpx.Response(status, headers=headers, json={"error": "x"})
        return httpx.Response(action, json={"error": "x"})

    clock = clock or Clock()
    router = LLMRouter(env=ALL_KEYS if env is None else env, usage=usage or MemoryUsageStore(),
                       transport=httpx.MockTransport(handler), clock=clock)
    return router, calls, clock


async def test_unconfigured_providers_are_skipped_cleanly():
    router, calls, _ = make_router({}, env={"MISTRAL_API_KEY": FAKE})
    result = await router.generate_json("screening_qa", "s", "u", Answer)
    assert result.provider == "mistral" and calls == ["mistral"]
    assert [a["outcome"] for a in result.attempts[:2]] == ["unconfigured", "unconfigured"]
    states = {p["provider"]: p["status"] for p in await router.status()}
    assert states == {"groq": "unconfigured", "gemini": "unconfigured", "mistral": "healthy",
                      "openrouter": "unconfigured", "cloudflare": "unconfigured", "github_models": "unconfigured",
                      "cerebras": "unconfigured"}


async def test_cloudflare_needs_account_id_and_github_accepts_github_token():
    router, _, _ = make_router({}, env={"CLOUDFLARE_API_TOKEN": FAKE, "GITHUB_TOKEN": FAKE})
    assert not router.providers["cloudflare"].configured
    assert "CLOUDFLARE_ACCOUNT_ID" in (router.providers["cloudflare"].problem or "")
    assert router.providers["github_models"].configured


async def test_no_keys_raises_exhausted_without_any_http():
    router, calls, _ = make_router({}, env={})
    assert not router.any_configured
    with pytest.raises(AllLLMProvidersExhaustedError) as exc:
        await router.generate_json("screening_qa", "s", "u", Answer)
    assert calls == [] and {a["outcome"] for a in exc.value.attempts} == {"unconfigured"}


@pytest.mark.parametrize("failure,outcome", [(429, "http_429"), (503, "http_503"), ("timeout", "timeout"),
                                             ("bad_json", "invalid_json:ValidationError"),
                                             ("prose", "invalid_json:ProviderResponseError")])
async def test_failover_to_next_provider(failure, outcome):
    router, calls, _ = make_router({"groq": failure})
    result = await router.generate_json("screening_qa", "s", "u", Answer)
    assert result.provider == "gemini" and calls == ["groq", "gemini"]
    assert result.attempts[0]["provider"] == "groq" and result.attempts[0]["outcome"] == outcome
    assert result.value.answer == "Yes" and result.input_tokens == 50 and result.output_tokens == 7


async def test_task_chain_order_differs_per_task():
    router, _calls, _ = make_router({})
    assert (await router.generate_json("jd_scoring", "s", "u", Answer)).provider == "gemini"
    assert (await router.generate_json("screening_qa", "s", "u", Answer)).provider == "groq"
    with pytest.raises(ValueError):
        await router.generate_json("unknown_task", "s", "u", Answer)


async def test_429_respects_retry_after_and_skips_during_cooldown():
    router, calls, clock = make_router({"groq": (429, {"retry-after": "120"})})
    await router.generate_json("screening_qa", "s", "u", Answer)
    calls.clear()
    clock.advance(100)
    await router.generate_json("screening_qa", "s", "u", Answer)
    assert calls == ["gemini"]  # groq still cooling down
    assert {p["provider"]: p["status"] for p in await router.status()}["groq"] == "cooldown"
    clock.advance(30)
    calls.clear()
    retried = await router.generate_json("screening_qa", "s", "u", Answer)
    assert calls[0] == "groq" and retried.provider == "gemini"  # retried after the cooldown (still 429)


async def test_circuit_opens_after_three_consecutive_failures_and_resets_on_success():
    state = {"fail": True}
    router, calls, clock = make_router({"groq": lambda n: 503 if state["fail"] else "ok"})
    for expected_cooldown in (10, 20, 300):
        result = await router.generate_json("screening_qa", "s", "u", Answer)
        assert result.attempts[0]["cooldown_sec"] == expected_cooldown
        clock.advance(expected_cooldown + 1 if expected_cooldown < 300 else 0)
    status = {p["provider"]: p for p in await router.status()}["groq"]
    assert status["status"] == "circuit_open" and status["consecutive_failures"] == 3
    assert status["last_error"] == "circuit_open:http_503"
    calls.clear()
    clock.advance(200)
    await router.generate_json("screening_qa", "s", "u", Answer)
    assert calls == ["gemini"]  # open circuit is skipped without an HTTP call
    clock.advance(101)
    state["fail"] = False
    calls.clear()
    assert (await router.generate_json("screening_qa", "s", "u", Answer)).provider == "groq"
    status = {p["provider"]: p for p in await router.status()}["groq"]
    assert status["status"] == "healthy" and status["consecutive_failures"] == 0 and status["last_error"] is None


async def test_auth_failure_opens_long_circuit():
    router, _, _ = make_router({"groq": 401})
    result = await router.generate_json("screening_qa", "s", "u", Answer)
    assert result.attempts[0]["outcome"] == "http_401_auth" and result.attempts[0]["cooldown_sec"] == 3600


async def test_local_rpm_and_rpd_caps_stop_before_exceeding_free_tier():
    usage = MemoryUsageStore()
    router, calls, clock = make_router({}, env={"OPENROUTER_API_KEY": FAKE, "MISTRAL_API_KEY": FAKE}, usage=usage)
    spec = PROVIDER_REGISTRY["openrouter"]
    router.chains["screening_qa"] = ("openrouter", "mistral")
    for _ in range(spec.rpm):
        assert (await router.generate_json("screening_qa", "s", "u", Answer)).provider == "openrouter"
    result = await router.generate_json("screening_qa", "s", "u", Answer)
    assert result.provider == "mistral" and result.attempts[0]["outcome"] == "local_cap_rpm"
    clock.advance(61)  # next minute: RPM frees up, RPD (45) still counts
    for _ in range(spec.rpd - spec.rpm):
        assert (await router.generate_json("screening_qa", "s", "u", Answer)).provider == "openrouter"
        clock.advance(4)
    clock.advance(61)
    result = await router.generate_json("screening_qa", "s", "u", Answer)
    assert result.attempts[0]["outcome"] == "local_cap_rpd"
    assert calls.count("openrouter") == spec.rpd  # never exceeded the daily cap
    snapshot = await usage.snapshot("openrouter", router.providers["openrouter"].model, clock())
    assert snapshot.day_requests == spec.rpd and snapshot.day_input_tokens == 30 * spec.rpd


async def test_tpd_cap_counts_planned_tokens():
    router, _calls, _ = make_router({}, env={"GROQ_API_KEY": FAKE, "MISTRAL_API_KEY": FAKE})
    model = router.providers["groq"].model
    await router.usage.record("groq", model, router.clock(), input_tokens=89_900)
    result = await router.generate_json("screening_qa", "s", "u" * 2000, Answer)
    assert result.provider == "mistral" and result.attempts[0]["outcome"] == "local_cap_tpd"


async def test_all_providers_failing_raises_exhausted_with_attempt_log():
    router, calls, _ = make_router({name: 503 for name in HOSTS.values()})
    with pytest.raises(AllLLMProvidersExhaustedError) as exc:
        await router.generate_json("screening_qa", "s", "u", Answer)
    assert len(calls) == 6 and [a["outcome"] for a in exc.value.attempts if a["outcome"] != "unconfigured"] \
        == ["http_503"] * 6


def test_wire_formats_for_every_provider():
    for name, spec in PROVIDER_REGISTRY.items():
        config = resolve_provider(spec, WITH_CEREBRAS)
        request = build_request(config, "sys", "user", max_output_tokens=50)
        assert request.url.startswith("https://") and FAKE not in request.url  # key never in the URL
        assert FAKE in json.dumps(request.headers)
        parsed = parse_response(config, ok_body(name))
        assert json.loads(parsed.text) == GOOD
    gemini = build_request(resolve_provider(PROVIDER_REGISTRY["gemini"], ALL_KEYS), "s", "u", max_output_tokens=9)
    assert gemini.body["generationConfig"]["responseMimeType"] == "application/json"
    assert "x-goog-api-key" in gemini.headers
    cloudflare = build_request(resolve_provider(PROVIDER_REGISTRY["cloudflare"], ALL_KEYS), "s", "u",
                               max_output_tokens=9)
    assert "/accounts/acct-test/ai/run/@cf/" in cloudflare.url
    groq = build_request(resolve_provider(PROVIDER_REGISTRY["groq"], ALL_KEYS), "s", "u", max_output_tokens=9)
    assert groq.body["response_format"] == {"type": "json_object"}


async def test_status_never_exposes_keys():
    router, _, _ = make_router({})
    assert FAKE not in json.dumps(await router.status(), default=str)


# --- persisted usage on a disposable PostgreSQL -------------------------------------
@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if PG_BIN is None or os.environ.get("SKIP_DISPOSABLE_POSTGRES") == "1":
        pytest.skip("local PostgreSQL binaries not available")
    tmp = tmp_path_factory.mktemp("pgusage")
    data, port = tmp / "pg", free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust"],
                   check=True, capture_output=True)
    server = subprocess.Popen([str(PG_BIN / "postgres"), "-D", str(data), "-p", str(port), "-k", "",
                               "-c", "listen_addresses=127.0.0.1"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    psql = [str(PG_BIN / "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q"]
    try:
        for _ in range(100):
            if subprocess.run([*psql, "-c", "SELECT 1"], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(0.1)
        subprocess.run([*psql, "-c", BOOTSTRAP], check=True, capture_output=True)
        migration = tmp / "004.sql"
        migration.write_text(strip_pgvector(MIGRATION.read_text()))
        subprocess.run([*psql, "-f", str(migration)], check=True, capture_output=True, text=True)
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest_asyncio.fixture
async def connection(database):
    import asyncpg

    conn = await asyncpg.connect(database)
    await conn.execute("TRUNCATE public.llm_provider_usage")
    yield conn
    await conn.close()


async def test_postgres_usage_persists_buckets_and_circuit_across_restart(connection, database):
    import asyncpg

    clock = Clock()
    router, _calls, _ = make_router({"groq": 503}, usage=PostgresUsageStore(connection), clock=clock)
    await router.generate_json("screening_qa", "s", "u", Answer)
    await router.generate_json("screening_qa", "s", "u", Answer)
    rows = await connection.fetch(
        "SELECT provider, window_type, requests, input_tokens, circuit_open_until, last_error "
        "FROM public.llm_provider_usage ORDER BY provider, window_type")
    by_key = {(r["provider"], r["window_type"]): r for r in rows}
    assert by_key[("gemini", "day")]["requests"] == 2 and by_key[("gemini", "minute")]["requests"] == 2
    assert by_key[("gemini", "day")]["input_tokens"] == 100
    assert by_key[("groq", "day")]["requests"] == 1  # second call skipped groq (cooldown)
    assert by_key[("groq", "day")]["last_error"] == "http_503"
    assert by_key[("groq", "day")]["circuit_open_until"] > clock()
    fresh = await asyncpg.connect(database)  # a restarted worker still honours the cooldown
    try:
        restarted, calls2, _ = make_router({}, usage=PostgresUsageStore(fresh), clock=clock)
        assert (await restarted.generate_json("screening_qa", "s", "u", Answer)).provider == "gemini"
        assert calls2 == ["gemini"]
    finally:
        await fresh.close()
