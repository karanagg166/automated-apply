"""Shared v2 env loader: precedence, free-key aliases, zero secret leakage, and the ai-test probe."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.ai_v2.probe import PROBE_USER, classify_status, probe_all
from backend.app.ai_v2.providers import PROVIDER_REGISTRY, resolve_provider
from backend.app.ai_v2.router import LLMRouter
from backend.app.browser_v2 import env_loader
from backend.app.browser_v2.env_loader import (
    KEY_ALIASES,
    EnvLayer,
    apply_aliases,
    env_layers,
    key_sources,
    mask,
    merge_layers,
)

FAKE = "TEST_FAKE_TOKEN_ONLY"


def write(path: Path, **values: str) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return path


@pytest.fixture
def files(tmp_path):
    root = write(tmp_path / "root.env", GROQ_API_KEY=FAKE + "_root", SHARED="root", ROOT_ONLY="r")
    backend = write(tmp_path / "backend.env", GROQ_API_KEY=FAKE + "_backend", SHARED="backend", BACKEND_ONLY="b")
    private = write(tmp_path / "phase1.private.env", SHARED="private", PRIVATE_ONLY="p")
    return root, backend, private


def layers(files, environ):
    root, backend, private = files
    return env_layers(private, environ=environ, repo_files=(("root .env", root), ("backend/.env", backend)))


def test_precedence_process_over_private_over_backend_over_root(files):
    merged = merge_layers(layers(files, {"SHARED": "process"}))
    assert merged["SHARED"] == "process"
    assert merged["ROOT_ONLY"] == "r" and merged["BACKEND_ONLY"] == "b" and merged["PRIVATE_ONLY"] == "p"
    assert merged["GROQ_API_KEY"] == FAKE + "_backend"  # backend/.env beats root .env
    merged = merge_layers(layers(files, {}))
    assert merged["SHARED"] == "private"


def test_layer_order_and_labels(files):
    labels = [layer.label for layer in layers(files, {})]
    assert labels == ["root .env", "backend/.env", "private env file", "process env"]


def test_repo_files_switch_disables_repo_dotenv(files):
    labels = [layer.label for layer in layers(files, {env_loader.REPO_FILES_SWITCH: "0"})]
    assert labels == ["private env file", "process env"]


def test_missing_files_are_skipped(tmp_path):
    stack = env_layers(tmp_path / "nope.env", environ={},
                       repo_files=(("root .env", tmp_path / "a"), ("backend/.env", tmp_path / "b")))
    # Only the process layer (plus the default private file, if the owner machine has one).
    assert stack[-1].label == "process env"
    assert all(layer.path is None or layer.path.is_file() for layer in stack)


@pytest.mark.parametrize("alias,canonical", [
    ("GOOGLE_AI_API_KEY", "GEMINI_API_KEY"), ("GOOGLE_API_KEY", "GEMINI_API_KEY"), ("GROQ_KEY", "GROQ_API_KEY"),
    ("OPENROUTER_KEY", "OPENROUTER_API_KEY"), ("CF_API_TOKEN", "CLOUDFLARE_API_TOKEN"),
    ("CF_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID"), ("CEREBRAS_KEY", "CEREBRAS_API_KEY"),
    ("MISTRAL_KEY", "MISTRAL_API_KEY"), ("GH_MODELS_TOKEN", "GITHUB_MODELS_TOKEN"),
])
def test_aliases_fill_canonical_names(alias, canonical):
    assert alias in KEY_ALIASES[canonical]
    assert apply_aliases({alias: FAKE})[canonical] == FAKE


def test_canonical_value_wins_over_alias():
    values = apply_aliases({"GEMINI_API_KEY": FAKE + "_canonical", "GOOGLE_AI_API_KEY": FAKE + "_alias"})
    assert values["GEMINI_API_KEY"] == FAKE + "_canonical"


def test_blank_canonical_falls_back_to_alias():
    assert apply_aliases({"GROQ_API_KEY": "  ", "GROQ_KEY": FAKE})["GROQ_API_KEY"] == FAKE


def test_aliased_key_configures_the_provider():
    env = apply_aliases({"GOOGLE_AI_API_KEY": FAKE, "CF_API_TOKEN": FAKE, "CF_ACCOUNT_ID": "acct123"})
    assert resolve_provider(PROVIDER_REGISTRY["gemini"], env).configured
    assert resolve_provider(PROVIDER_REGISTRY["cloudflare"], env).configured


def test_openrouter_stays_free_only_even_via_alias():
    env = apply_aliases({"OPENROUTER_KEY": FAKE, "OPENROUTER_MODEL": "openai/gpt-4o"})
    config = resolve_provider(PROVIDER_REGISTRY["openrouter"], env)
    assert not config.configured and "paid model refused" in (config.problem or "")


def test_openrouter_default_model_is_a_free_model():
    assert PROVIDER_REGISTRY["openrouter"].default_model.endswith(":free")
    assert "llama-3.3-70b-instruct:free" not in PROVIDER_REGISTRY["openrouter"].default_model  # delisted live


def test_key_sources_report_names_and_layers_never_values(files):
    stack = layers(files, {"CF_API_TOKEN": FAKE})
    sources = key_sources(["GROQ_API_KEY", "CLOUDFLARE_API_TOKEN", "MISTRAL_API_KEY"], layers=stack)
    assert sources == {"GROQ_API_KEY": "backend/.env", "CLOUDFLARE_API_TOKEN": "process env via CF_API_TOKEN",
                       "MISTRAL_API_KEY": None}
    assert FAKE not in json.dumps(sources)


def test_mask_and_layer_repr_never_print_values():
    assert mask(FAKE) == "configured" and mask("") == "missing" and mask(None) == "missing"
    layer = EnvLayer("process env", None, {"GROQ_API_KEY": FAKE})
    assert FAKE not in repr(layer)


def test_router_and_subsystems_share_the_loader(monkeypatch, tmp_path):
    private = write(tmp_path / "p.env", GROQ_KEY=FAKE, TELEGRAM_BOT_TOKEN="123456:" + "A" * 35,
                    TELEGRAM_OWNER_CHAT_ID="42", GMAIL_IMAP_EMAIL="owner@example.com",
                    GMAIL_IMAP_APP_PASSWORD=FAKE, APOLLO_API_KEY=FAKE)
    for name in ("GROQ_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_ID", "TELEGRAM_V2_DISABLED",
                 "GMAIL_IMAP_EMAIL", "GMAIL_IMAP_APP_PASSWORD", "APOLLO_API_KEY", "ENRICHMENT_V2_DISABLED"):
        monkeypatch.delenv(name, raising=False)  # conftest blanks owner keys; a blank process value wins
    monkeypatch.setenv("AUTOMATED_APPLY_ENV_FILE", str(private))
    monkeypatch.setenv(env_loader.REPO_FILES_SWITCH, "0")
    from backend.app.ai_v2.router import load_env
    from backend.app.enrichment_v2.config import EnrichmentConfig
    from backend.app.mail_v2.config import MailConfig
    from backend.app.telegram_v2.config import TelegramConfig

    env = load_env()
    assert env["GROQ_API_KEY"] == FAKE  # alias applied through the router entry point
    assert LLMRouter(env=env).providers["groq"].configured
    assert TelegramConfig.from_env().configured
    assert MailConfig.from_env().imap_configured
    assert EnrichmentConfig.from_env().public()["providers"]["apollo"]["configured"] is True


class Recorder:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.requests = status, body, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "openrouter.ai" and request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "google/gemma-4-31b-it:free"}, {"id": "x/paid"}]})
        if self.body is not None:
            return httpx.Response(self.status, json=self.body)
        if "generativelanguage" in str(request.url):
            return httpx.Response(self.status, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})
        return httpx.Response(self.status, json={"choices": [{"message": {"content": '{"ok": true}'}}]})


async def test_ai_test_probe_ok_schema_and_zero_pii():
    router = LLMRouter(env={"GROQ_API_KEY": FAKE, "GEMINI_API_KEY": FAKE})
    recorder = Recorder()
    report = await probe_all(router.providers, transport=httpx.MockTransport(recorder))
    rows = {row["provider"]: row for row in report["providers"]}
    assert rows["groq"]["status"] == "OK" and rows["groq"]["json_valid"] is True
    assert rows["gemini"]["status"] == "OK" and rows["gemini"]["json_valid"] is True
    assert rows["mistral"]["status"] == "unconfigured"
    assert report["configured"] == 2 and report["passed"] == 2
    assert report["openrouter_catalog"]["model_listed"] is True
    assert set(rows["groq"]) >= {"provider", "model", "status", "latency_ms", "json_valid"}
    posts = [r for r in recorder.requests if r.method == "POST"]
    assert len(posts) == 2  # one tiny request per configured provider, sequential
    assert all(PROBE_USER.split("{")[0].encode() in r.content and b"@" not in r.content for r in posts)
    assert FAKE not in json.dumps(report)


@pytest.mark.parametrize("status,expected", [(401, "401"), (403, "403"), (429, "429"), (503, "5xx")])
async def test_ai_test_probe_http_errors(status, expected):
    router = LLMRouter(env={"GROQ_API_KEY": FAKE})
    report = await probe_all(router.providers, only=["groq"],
                             transport=httpx.MockTransport(Recorder(status=status, body={"error": "x"})))
    assert report["providers"][0]["status"] == expected and report["providers"][0]["json_valid"] is False
    assert classify_status(status) == expected


async def test_ai_test_probe_invalid_json_is_reported():
    router = LLMRouter(env={"GROQ_API_KEY": FAKE})
    bad = {"choices": [{"message": {"content": "sure thing"}}]}
    report = await probe_all(router.providers, only=["groq"], transport=httpx.MockTransport(Recorder(body=bad)))
    row = report["providers"][0]
    assert row["status"] == "OK" and row["json_valid"] is False and row["error"].startswith("invalid_json")
