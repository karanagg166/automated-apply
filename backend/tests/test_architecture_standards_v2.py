"""Phase 9A architecture guardrail for the Python v2 runtime.

Enforces, statically (no imports executed):
  (a) a LOC ceiling on every v2 module (hard 450, target 400 with justified exceptions),
  (b) v2 code reaches non-v2 ``backend.app`` code only through a small shared kernel,
  (c) no circular module-level imports between v2 modules,
  (d) module-level imports never point "up" the layer stack
      (domain -> store -> outbound adapters -> services -> transport).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "backend/app"
V2_PACKAGES = ("browser_v2", "ai_v2", "telegram_v2", "enrichment_v2", "mail_v2", "agent_v2", "events_v2")
V2_EXTRA = ("api/v1/automation_v2.py", "api/v1/v2")

HARD_CEILING = 450
TARGET = 400
# path (relative to backend/app) -> justification. Only pure data / JS snippet files may sit in 401..450.
LOC_EXCEPTIONS: dict[str, str] = {}

# The shared kernel v2 may import from the rest of backend.app (config, DB session, profile schema).
SHARED_KERNEL = (
    "backend.app.core.config",
    "backend.app.core.security",
    "backend.app.db.session",
    "backend.app.db.safety",
    "backend.app.schemas.candidate_profile",
    "backend.app.repositories.candidate_profile",
    "backend.app.operations.v2_schema",
    "backend.app.integrations.gmail.read_client",
)
# Emptied: v2 owns its feed HTTP clients (browser_v2/adapters/feed_clients).
KERNEL_DEBT: tuple[str, ...] = ()

# Layer ranks by module-name prefix (longest prefix wins). Unranked modules are not checked.
DOMAIN, STORE, ADAPTER, SERVICE, TRANSPORT = range(5)
LAYERS: dict[str, int] = {
    "backend.app.browser_v2.state": DOMAIN,
    "backend.app.browser_v2.portals": DOMAIN,
    "backend.app.browser_v2.rules": DOMAIN,
    "backend.app.browser_v2.tech_terms": DOMAIN,
    "backend.app.browser_v2.answers": DOMAIN,
    "backend.app.browser_v2.domain": DOMAIN,
    "backend.app.browser_v2.outcomes": DOMAIN,
    "backend.app.browser_v2.priority": DOMAIN,
    "backend.app.browser_v2.schemas": DOMAIN,
    "backend.app.browser_v2.config": DOMAIN,
    "backend.app.browser_v2.env_loader": DOMAIN,
    "backend.app.ai_v2.pii": DOMAIN,
    "backend.app.ai_v2.schemas": DOMAIN,
    "backend.app.ai_v2.semantic_cache.models": DOMAIN,
    # adapters/base.py is the adapter *port* (DTOs + Protocol); it belongs to the domain.
    "backend.app.browser_v2.adapters.base": DOMAIN,
    "backend.app.browser_v2.store": STORE,
    "backend.app.ai_v2.semantic_cache": STORE,
    "backend.app.ai_v2.usage": STORE,
    "backend.app.enrichment_v2.store": STORE,
    "backend.app.browser_v2.adapters": ADAPTER,
    "backend.app.browser_v2.manager": ADAPTER,
    "backend.app.browser_v2.profile": ADAPTER,
    "backend.app.browser_v2.forms": ADAPTER,
    "backend.app.browser_v2.receipts": ADAPTER,
    "backend.app.browser_v2.resume": ADAPTER,
    "backend.app.ai_v2.providers": ADAPTER,
    "backend.app.ai_v2.embeddings": STORE,  # embedding backend used by the semantic-cache store
    "backend.app.telegram_v2.client": ADAPTER,
    "backend.app.browser_v2.service": SERVICE,
    "backend.app.browser_v2.worker": SERVICE,
    "backend.app.browser_v2.quota": SERVICE,
    "backend.app.browser_v2.hitl": SERVICE,
    "backend.app.browser_v2.digest": SERVICE,
    "backend.app.browser_v2.profile_sync": SERVICE,
    "backend.app.browser_v2.watchers": SERVICE,
    "backend.app.telegram_v2.notify_router": SERVICE,
    "backend.app.telegram_v2.notify_policy": DOMAIN,
    "backend.app.browser_v2.redact": DOMAIN,
    "backend.app.telegram_v2.agent_bridge": SERVICE,
    # Phase 9D: pure value objects + diff are domain; the per-portal profile adapters are outbound adapters.
    "backend.app.browser_v2.profile_sync.models": DOMAIN,
    "backend.app.browser_v2.profile_sync.diff": DOMAIN,
    "backend.app.browser_v2.profile_sync.adapters": ADAPTER,
    "backend.app.agent_v2": SERVICE,
    "backend.app.ai_v2.router": SERVICE,
    "backend.app.ai_v2.runtime": SERVICE,
    "backend.app.telegram_v2.bot": SERVICE,
    "backend.app.telegram_v2.base": SERVICE,
    "backend.app.telegram_v2.polling": SERVICE,
    "backend.app.telegram_v2.routing": SERVICE,
    "backend.app.telegram_v2.commands": SERVICE,
    "backend.app.telegram_v2.outbound": SERVICE,
    "backend.app.telegram_v2.formatting": ADAPTER,
    "backend.app.telegram_v2.config": DOMAIN,
    "backend.app.browser_v2.cli": TRANSPORT,
    "backend.app.browser_v2.browser_mcp": TRANSPORT,
    "backend.app.api.v1.automation_v2": TRANSPORT,
    "backend.app.api.v1.v2": TRANSPORT,
}
# (importer, imported) pairs tolerated until Phase 9E; must be empty at the end of Phase 9.
KNOWN_LAYER_DEBT: frozenset[tuple[str, str]] = frozenset()


def v2_files() -> list[Path]:
    files = [p for pkg in V2_PACKAGES for p in sorted((APP / pkg).rglob("*.py"))]
    for extra in V2_EXTRA:
        target = APP / extra
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.exists():
            files.append(target)
    return [f for f in files if "__pycache__" not in f.parts]


def module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def resolve(node: ast.ImportFrom, current: str, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    base = current.split(".") if is_package else current.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def _module_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements executed at import time (skips function bodies and TYPE_CHECKING blocks)."""
    for stmt in body:
        if isinstance(stmt, ast.If):
            if _is_type_checking(stmt):
                yield from _module_level(stmt.orelse)
                continue
            yield from _module_level(stmt.body)
            yield from _module_level(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            for block in (stmt.body, stmt.orelse, stmt.finalbody, *[h.body for h in stmt.handlers]):
                yield from _module_level(block)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        else:
            yield stmt


def imports(path: Path, *, module_level_only: bool) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Yield (imported module, imported names) for every import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    current = module_name(path)
    is_package = path.name == "__init__.py"
    nodes = _module_level(tree.body) if module_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, ()
        elif isinstance(node, ast.ImportFrom):
            yield resolve(node, current, is_package), tuple(a.name for a in node.names)


def _known_modules() -> set[str]:
    return {module_name(p) for p in v2_files()}


def _targets(module: str, names: tuple[str, ...], known: set[str]) -> set[str]:
    """`from pkg import sub` points at pkg.sub when that is a module, else at pkg itself."""
    out = set()
    for name in names:
        candidate = f"{module}.{name}"
        if candidate in known:
            out.add(candidate)
        elif module in known:
            out.add(module)
    if not names and module in known:
        out.add(module)
    return out


def _is_v2(name: str) -> bool:
    return any(name == f"backend.app.{pkg}" or name.startswith(f"backend.app.{pkg}.") for pkg in V2_PACKAGES) \
        or name.startswith(("backend.app.api.v1.automation_v2", "backend.app.api.v1.v2"))


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def rank(module: str) -> int | None:
    best = None
    for prefix, value in LAYERS.items():
        if (module == prefix or module.startswith(prefix + ".")) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, value)
    return best[1] if best else None


def test_every_v2_module_is_within_the_loc_ceiling() -> None:
    over_hard, over_target = [], []
    for path in v2_files():
        rel = str(path.relative_to(APP))
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > HARD_CEILING:
            over_hard.append(f"{rel}: {lines}")
        elif lines > TARGET and rel not in LOC_EXCEPTIONS:
            over_target.append(f"{rel}: {lines}")
    assert not over_hard, f"v2 modules above the {HARD_CEILING}-line hard ceiling: {over_hard}"
    assert not over_target, f"v2 modules above {TARGET} lines without a LOC_EXCEPTIONS entry: {over_target}"


def test_loc_exceptions_are_real_and_justified() -> None:
    for rel, reason in LOC_EXCEPTIONS.items():
        path = APP / rel
        assert path.exists(), f"stale LOC exception: {rel}"
        assert len(reason) >= 20, f"LOC exception for {rel} needs a real justification"


def test_v2_reaches_legacy_code_only_through_the_shared_kernel() -> None:
    allowed = SHARED_KERNEL + KERNEL_DEBT
    offenders = []
    for path in v2_files():
        for module, _names in imports(path, module_level_only=False):
            if module.startswith("backend.app") and not _is_v2(module) and module != "backend.app" \
                    and not _under(module, allowed):
                offenders.append(f"{path.relative_to(REPO)} -> {module}")
    assert not offenders, "v2 imports outside the shared kernel:\n" + "\n".join(sorted(set(offenders)))


def _graph() -> dict[str, set[str]]:
    known = _known_modules()
    graph: dict[str, set[str]] = {m: set() for m in known}
    for path in v2_files():
        current = module_name(path)
        for module, names in imports(path, module_level_only=True):
            for target in _targets(module, names, known):
                if target != current:
                    graph[current].add(target)
    return graph


def _strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []
    counter = [0]

    def visit(node: str) -> None:
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in graph.get(node, ()):
            if nxt not in index:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return result


def test_no_circular_module_level_imports_between_v2_modules() -> None:
    cycles = _strongly_connected(_graph())
    assert not cycles, "circular module-level imports:\n" + "\n".join(" <-> ".join(c) for c in cycles)


def test_module_level_imports_never_point_up_the_layer_stack() -> None:
    violations = set()
    for importer, targets in _graph().items():
        low = rank(importer)
        if low is None:
            continue
        for target in targets:
            high = rank(target)
            if high is not None and high > low and (importer, target) not in KNOWN_LAYER_DEBT:
                violations.add((importer, target))
    assert not violations, "layering violations:\n" + "\n".join(f"{a} -> {b}" for a, b in sorted(violations))


def test_known_layer_debt_is_not_stale() -> None:
    graph = _graph()
    stale = [pair for pair in KNOWN_LAYER_DEBT if pair[1] not in graph.get(pair[0], set())]
    assert not stale, f"remove stale KNOWN_LAYER_DEBT entries: {stale}"
