"""Single shared v2 env loader (ai_v2, mail_v2, enrichment_v2, telegram_v2, events_v2, browser_v2, cli).

Owner rule (2026-11-26): every env value lives in the project directory. Precedence, highest first:
    1. process environment
    2. an explicit env file / $AUTOMATED_APPLY_ENV_FILE (optional override)
    3. <repo>/.env  (the one project env file, gitignored)
Free-key aliases (e.g. GOOGLE_AI_API_KEY -> GEMINI_API_KEY) fill a canonical name only when
the canonical name is absent at every layer. Values are never logged or returned by the
reporting helpers: `key_sources()` reports key NAMES + the layer label only.

Set AUTOMATED_APPLY_ENV_REPO_FILES=0 to ignore <repo>/.env (tests/CI).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.browser_v2.config import (
    ENV_FILE_VARIABLE,
    REPO_FILES_SWITCH,
    REPO_ROOT,
)

ROOT_DOTENV = REPO_ROOT / ".env"
_FALSE = {"0", "false", "no", "off"}

# canonical name -> accepted aliases (first non-empty alias wins). Free-tier names only.
KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "GROQ_API_KEY": ("GROQ_KEY", "GROQ_TOKEN"),
    "GEMINI_API_KEY": ("GOOGLE_AI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY",
                       "GEMINI_KEY", "GOOGLE_API_KEY"),
    "MISTRAL_API_KEY": ("MISTRAL_KEY",),
    "OPENROUTER_API_KEY": ("OPENROUTER_KEY", "OPEN_ROUTER_API_KEY"),
    "CLOUDFLARE_API_TOKEN": ("CF_API_TOKEN", "CLOUDFLARE_AI_TOKEN", "CLOUDFLARE_WORKERS_AI_TOKEN",
                             "CF_WORKERS_AI_TOKEN"),
    "CLOUDFLARE_ACCOUNT_ID": ("CF_ACCOUNT_ID",),
    "GITHUB_MODELS_TOKEN": ("GH_MODELS_TOKEN", "GITHUB_MODELS_PAT"),
    "CEREBRAS_API_KEY": ("CEREBRAS_KEY",),
}


@dataclass(frozen=True)
class EnvLayer:
    label: str
    path: Path | None
    values: dict[str, str] = field(repr=False)


def _read_dotenv(path: Path) -> dict[str, str]:
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if isinstance(v, str)}


def _repo_files_enabled(environ: Mapping[str, str]) -> bool:
    return (environ.get(REPO_FILES_SWITCH) or "").strip().lower() not in _FALSE


def env_layers(explicit: str | os.PathLike[str] | None = None, *,
               environ: Mapping[str, str] | None = None,
               repo_files: Iterable[tuple[str, Path]] | None = None) -> list[EnvLayer]:
    """Layers lowest -> highest precedence (later layers override earlier ones)."""
    process = dict(os.environ if environ is None else environ)
    layers: list[EnvLayer] = []
    if _repo_files_enabled(process):
        for label, path in (repo_files if repo_files is not None else (("project .env", ROOT_DOTENV),)):
            if path.is_file():
                layers.append(EnvLayer(label, path, _read_dotenv(path)))
    override = next((Path(c).expanduser() for c in (explicit, process.get(ENV_FILE_VARIABLE))
                     if c and Path(c).expanduser().is_file()), None)
    if override is not None and all(layer.path != override for layer in layers):
        layers.append(EnvLayer("override env file", override, _read_dotenv(override)))
    layers.append(EnvLayer("process env", None, process))
    return layers


def apply_aliases(values: dict[str, str]) -> dict[str, str]:
    """Fill canonical key names from aliases when the canonical value is empty/absent."""
    for canonical, aliases in KEY_ALIASES.items():
        if (values.get(canonical) or "").strip():
            continue
        alias_value = next((values[a] for a in aliases if (values.get(a) or "").strip()), None)
        if alias_value is not None:
            values[canonical] = alias_value
    return values


def merge_layers(layers: Iterable[EnvLayer]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for layer in layers:
        merged.update(layer.values)
    return apply_aliases(merged)


def load_env(explicit: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """The one merged env mapping every v2 subsystem reads."""
    return merge_layers(env_layers(explicit))


def key_sources(names: Iterable[str], explicit: str | os.PathLike[str] | None = None, *,
                layers: list[EnvLayer] | None = None) -> dict[str, str | None]:
    """name -> label of the winning layer ("<layer> via ALIAS" for aliases), or None. Never values."""
    stack = layers if layers is not None else env_layers(explicit)
    result: dict[str, str | None] = {}
    for name in names:
        result[name] = _winning_layer(stack, name)
        if result[name] is None:
            for alias in KEY_ALIASES.get(name, ()):
                found = _winning_layer(stack, alias)
                if found is not None:
                    result[name] = f"{found} via {alias}"
                    break
    return result


def _winning_layer(layers: list[EnvLayer], name: str) -> str | None:
    for layer in reversed(layers):
        if (layer.values.get(name) or "").strip():
            return layer.label
    return None


def mask(value: str | None) -> str:
    """Presence-only marker for reports: never any character of the secret."""
    return "configured" if (value or "").strip() else "missing"
