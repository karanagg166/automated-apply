"""Phase 7 A.1: the seven ``*_v2`` packages (plus the v2 REST router) never load frozen
legacy group-B code (``backend.app.execution``, ``backend.app.browser``,
``backend.app.agent``, ``backend.app.mcp_server``) — neither by direct import nor
transitively through shared core modules — so v1 can be retired without touching v2."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.app.core import origin_policy
from backend.scripts import cleanup_legacy_v1 as cleanup

REPO = Path(__file__).resolve().parents[2]
V2_PACKAGES = (
    "browser_v2",
    "ai_v2",
    "telegram_v2",
    "enrichment_v2",
    "mail_v2",
    "agent_v2",
    "events_v2",
)
V2_EXTRA_FILES = ("backend/app/api/v1/automation_v2.py",)
LEGACY = (
    "backend.app.execution",
    "backend.app.browser",
    "backend.app.agent",
    "backend.app.mcp_server",
)


def v2_files() -> list[Path]:
    files = [p for pkg in V2_PACKAGES for p in sorted((REPO / "backend/app" / pkg).rglob("*.py"))]
    return files + [REPO / f for f in V2_EXTRA_FILES]


def module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def is_legacy(name: str) -> bool:
    return any(name == legacy or name.startswith(legacy + ".") for legacy in LEGACY)


def resolve(node: ast.ImportFrom, current: str, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    base = current.split(".") if is_package else current.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def test_every_v2_package_exists() -> None:
    for pkg in V2_PACKAGES:
        assert (REPO / "backend/app" / pkg / "__init__.py").is_file(), pkg
    assert len(v2_files()) > 40


def test_no_v2_file_imports_legacy_group_b_directly() -> None:
    offenders: list[str] = []
    for path in v2_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        current = module_name(path)
        for node in ast.walk(tree):  # includes function-local (lazy) imports
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = resolve(node, current, path.name == "__init__.py")
                names = [target, *(f"{target}.{alias.name}" for alias in node.names)]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names = [node.args[0].value]
            for name in names:
                # `from backend.app import browser_v2` yields "backend.app.browser_v2": not legacy.
                if is_legacy(name):
                    offenders.append(f"{path.relative_to(REPO)}:{getattr(node, 'lineno', 0)} -> {name}")
    assert offenders == []


def test_v2_files_are_not_cleanup_blockers() -> None:
    """cleanup_legacy_v1 greps text (docstrings included); v2 must never block group B."""
    v2 = {str(p.relative_to(REPO)) for p in v2_files()}
    hits: list[str] = []
    for legacy in ("backend/app/execution", "backend/app/browser", "backend/app/agent", "backend/app/mcp_server.py"):
        pattern = cleanup.module_pattern(legacy)
        assert pattern is not None
        found = subprocess.run(
            ["git", "grep", "-l", "-E", pattern, "--", *sorted(v2)],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        hits += [f"{legacy}: {line}" for line in found.stdout.split() if line in v2]
    assert hits == []


def test_importing_every_v2_module_loads_no_legacy_module_transitively() -> None:
    modules = [module_name(p) for p in v2_files()]
    script = (
        "import importlib, json, sys\n"
        f"mods = {modules!r}\n"
        "failed = {}\n"
        "for m in mods:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except Exception as exc:\n"
        "        failed[m] = repr(exc)[:200]\n"
        f"legacy = sorted(k for k in sys.modules if any(k == l or k.startswith(l + '.') for l in {LEGACY!r}))\n"
        "print(json.dumps({'failed': failed, 'legacy': legacy}))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO, env=env, capture_output=True, text=True, check=True, timeout=180,
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["failed"] == {}
    assert result["legacy"] == []


@pytest.mark.parametrize(
    ("value", "testing"),
    [
        ("https://cdn.example.com", False),
        ("https://cdn.example.com/", False),
        ("https://cdn.example.com:8443", False),
        ("http://127.0.0.1:9000", True),
        ("http://127.0.0.1:9000", False),
        ("http://cdn.example.com", False),
        ("https://user:pw@cdn.example.com", False),
        ("https://cdn.example.com/path", False),
        ("https://cdn.example.com?q=1", False),
        ("https://www.naukri.com", False),
        ("https://jobs.linkedin.com", False),
        ("https://10.0.0.5", False),
        ("https://intranet.local", False),
        ("https://cdn.example.com.", False),
        ("https://localhost", False),
    ],
)
def test_origin_policy_matches_frozen_legacy_asset_origin(value: str, testing: bool) -> None:
    legacy = pytest.importorskip("backend.app.browser.asset_policy")
    assert origin_policy.RESTRICTED_HOSTS == frozenset(legacy.RESTRICTED_HOSTS)

    def outcome(fn: object) -> tuple[str, str]:
        try:
            return ("ok", fn(value, testing=testing))  # type: ignore[operator]
        except ValueError as exc:
            return ("err", str(exc))

    assert outcome(origin_policy.asset_origin) == outcome(legacy.asset_origin)


@pytest.mark.parametrize(
    ("value", "testing"),
    [
        ("https://example.com", False),
        ("https://example.com/careers", False),
        ("https://example.com/about/team.html", False),
        ("https://example.com/api/jobs", False),
        ("https://example.com/login", False),
        ("https://example.com/robots.txt", False),
        ("https://example.com/careers?x=1", False),
        ("https://example.com/../etc", False),
        ("https://example.com//double", False),
        ("http://127.0.0.1:8080/about", True),
        ("https://www.naukri.com/careers", False),
    ],
)
def test_origin_policy_matches_frozen_legacy_source_url(value: str, testing: bool) -> None:
    legacy = pytest.importorskip("backend.app.browser.company_source_policy")

    def outcome(fn: object) -> tuple[str, str]:
        try:
            return ("ok", fn(value, testing=testing))  # type: ignore[operator]
        except ValueError as exc:
            return ("err", str(exc))

    assert outcome(origin_policy.source_url) == outcome(legacy.source_url)


def test_settings_still_normalizes_origins_via_core_policy() -> None:
    from backend.app.core.config import Settings

    overrides: dict[str, Any] = {
        "BROWSER_ASSET_ORIGINS": ["https://cdn.example.com/", "https://cdn.example.com"],
        "COMPANY_SOURCE_URLS": ["https://example.com/careers"],
    }
    settings = Settings(**overrides)
    assert settings.BROWSER_ASSET_ORIGINS == ["https://cdn.example.com:443"]
    assert settings.COMPANY_SOURCE_URLS == ["https://example.com:443/careers"]
    with pytest.raises(ValueError):
        Settings(**{**overrides, "BROWSER_ASSET_ORIGINS": ["https://www.naukri.com"]})
