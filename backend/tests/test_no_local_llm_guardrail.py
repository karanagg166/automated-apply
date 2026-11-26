"""AGENTS.md §1.2: the v2 AI layer never routes to a local generative LLM.

Only the local CPU embedding model (fastembed bge-small) may run on this Mac.
"""

import ast
import re
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.ai_v2.providers import (
    PROVIDER_REGISTRY,
    TASK_CHAINS,
    LocalLLMForbiddenError,
    ProviderSpec,
    assert_remote_free_endpoint,
    resolve_provider,
    validate_registry,
)
from backend.app.ai_v2.router import LLMRouter

ROOT = Path(__file__).resolve().parents[1] / "app"
V2_PACKAGES = (ROOT / "ai_v2", ROOT / "browser_v2", ROOT / "telegram_v2", ROOT / "enrichment_v2", ROOT / "mail_v2",
               ROOT / "agent_v2", ROOT / "events_v2")  # Phase 6A packages included
LOCAL_RUNTIME_MODULES = {"ollama", "llama_cpp", "llama_cpp_python", "gpt4all", "vllm", "mlx_lm", "ctransformers",
                         "transformers", "lmstudio", "exllamav2"}
LEGACY_AI_PREFIX = "backend.app.ai"


def v2_sources():
    for package in V2_PACKAGES:
        yield from sorted(package.rglob("*.py"))


def test_registry_has_exactly_the_eight_free_remote_providers():
    # 2026-11-26 owner-approved: Cohere trial key added as the last-resort free fallback.
    assert set(PROVIDER_REGISTRY) == {"groq", "gemini", "mistral", "openrouter", "cloudflare", "github_models",
                                      "cerebras", "cohere"}
    validate_registry(PROVIDER_REGISTRY)
    for spec in PROVIDER_REGISTRY.values():
        assert spec.base_url.startswith("https://")
        assert not re.search(r"ollama|llama[._-]?cpp|localhost|127\.0\.0\.1", spec.base_url + spec.default_model)
    for chain in TASK_CHAINS.values():
        assert set(chain) <= set(PROVIDER_REGISTRY)


@pytest.mark.parametrize("url", [
    "http://localhost:11434/api/chat",              # Ollama default
    "https://127.0.0.1:8080/v1/chat/completions",   # llama.cpp server
    "https://192.168.1.20:1234/v1/chat/completions",  # LM Studio on the LAN
    "https://macbook.local/v1/chat/completions",
    "http://api.groq.com/openai/v1/chat/completions",  # plain HTTP
    "https://ollama.example.com/api/generate",
])
def test_local_or_insecure_endpoints_are_rejected(url):
    spec = replace(PROVIDER_REGISTRY["groq"], name="custom", base_url=url)
    with pytest.raises(LocalLLMForbiddenError):
        assert_remote_free_endpoint(spec)
    with pytest.raises(LocalLLMForbiddenError):
        LLMRouter(env={}, registry={"custom": spec}, chains={"screening_qa": ("custom",)})


@pytest.mark.parametrize("name,model", [("ollama", "llama3"), ("groq", "ollama/llama3"),
                                        ("groq", "llamafile-mistral"), ("groq", "vllm/qwen")])
def test_local_generative_names_and_models_are_rejected(name, model):
    spec = ProviderSpec(name, name, "openai", "https://api.example.com/v1/chat/completions", model,
                        ("X_KEY",), "X_MODEL", rpm=1, rpd=1, tpd=None)
    with pytest.raises(LocalLLMForbiddenError):
        assert_remote_free_endpoint(spec)


def test_model_env_override_cannot_select_a_local_model():
    with pytest.raises(LocalLLMForbiddenError):
        resolve_provider(PROVIDER_REGISTRY["groq"], {"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY",
                                                     "GROQ_MODEL": "ollama/llama3.1"})


def test_openrouter_paid_models_are_refused():
    config = resolve_provider(PROVIDER_REGISTRY["openrouter"], {"OPENROUTER_API_KEY": "TEST_FAKE_TOKEN_ONLY",
                                                                "OPENROUTER_MODEL": "openai/gpt-4o"})
    assert not config.configured and "paid model refused" in (config.problem or "")


def test_v2_code_never_imports_local_llm_runtimes_or_the_legacy_ai_layer():
    offenders = []
    for path in v2_sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in LOCAL_RUNTIME_MODULES or name == LEGACY_AI_PREFIX \
                        or name.startswith(LEGACY_AI_PREFIX + "."):
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert not offenders, offenders


def test_v2_sources_contain_no_local_llm_endpoints():
    pattern = re.compile(r"localhost:11434|/api/generate|OLLAMA_HOST|llama-server|LLAMA_CPP", re.IGNORECASE)
    hits = [str(p.relative_to(ROOT)) for p in v2_sources() if pattern.search(p.read_text())]
    assert not hits, hits


def test_only_the_embedding_model_runs_locally():
    from backend.app.ai_v2.embeddings import DEFAULT_MODEL, DIMENSIONS

    assert DEFAULT_MODEL == "BAAI/bge-small-en-v1.5" and DIMENSIONS == 384
    source = (ROOT / "ai_v2" / "embeddings.py").read_text()
    assert "TextEmbedding" in source and "generate" not in source.lower()


# --- Phase 6A: owner-deployed custom_cloud_llm slot is HTTPS + public host only ------------------
CUSTOM_OK = {"CUSTOM_CLOUD_LLM_BASE_URL": "https://owner--sft-model.modal.run/v1",
             "CUSTOM_CLOUD_LLM_API_KEY": "TEST_FAKE_TOKEN_ONLY", "CUSTOM_CLOUD_LLM_MODEL": "owner/qwen-sft"}


@pytest.mark.parametrize("url", [
    "http://owner--sft.modal.run/v1",              # plain HTTP
    "https://localhost:8000/v1",
    "https://127.0.0.1/v1",
    "https://127.1/v1",                             # loopback shorthand
    "https://10.0.0.7/v1",                          # private LAN
    "https://192.168.1.4:1234/v1",                  # LM Studio on the LAN
    "https://[::1]/v1",
    "https://macbook.local/v1",
    "https://nas.home.arpa/v1",
    "https://ollama.example.com/v1",                # local runtime marker
])
def test_custom_cloud_llm_rejects_local_private_or_insecure_endpoints(url):
    from backend.app.ai_v2.providers import custom_cloud_spec

    env = CUSTOM_OK | {"CUSTOM_CLOUD_LLM_BASE_URL": url}
    with pytest.raises(LocalLLMForbiddenError):
        custom_cloud_spec(env)
    router = LLMRouter(env=env)  # refused, never registered, worker keeps running
    assert "custom_cloud_llm" not in router.providers and "custom_cloud_llm" in router.rejected
    assert all("custom_cloud_llm" not in chain for chain in router.chains.values())


def test_custom_cloud_llm_rejects_local_model_names():
    from backend.app.ai_v2.providers import custom_cloud_spec

    with pytest.raises(LocalLLMForbiddenError):
        custom_cloud_spec(CUSTOM_OK | {"CUSTOM_CLOUD_LLM_MODEL": "ollama/llama3"})


async def test_custom_cloud_llm_is_three_env_vars_and_respects_priority():
    fallback = LLMRouter(env=CUSTOM_OK)
    assert fallback.providers["custom_cloud_llm"].configured
    assert fallback.providers["custom_cloud_llm"].spec.base_url == "https://owner--sft-model.modal.run/v1/chat/completions"
    assert fallback.chain("screening_qa")[-1] == "custom_cloud_llm"
    first = LLMRouter(env=CUSTOM_OK | {"CUSTOM_CLOUD_LLM_PRIORITY": "first"})
    assert all(chain[0] == "custom_cloud_llm" for chain in first.chains.values())
    status = {p["provider"]: p["status"] for p in await first.status()}
    assert status["custom_cloud_llm"] == "healthy"


def test_cerebras_is_a_free_remote_openai_compatible_provider():
    spec = PROVIDER_REGISTRY["cerebras"]
    assert spec.base_url == "https://api.cerebras.ai/v1/chat/completions" and spec.key_envs == ("CEREBRAS_API_KEY",)
    assert spec.tpd is not None and spec.tpd <= 1_000_000
    assert all("cerebras" in chain for chain in TASK_CHAINS.values())
