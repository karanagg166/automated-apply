"""Bounded repository readers and static technical evidence extraction.

Only explicitly authorized repository mappings are read. Git is invoked with
fixed arguments and no shell; source text is never evaluated or executed.
"""

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from pydantic import Field, StringConstraints, model_validator

from backend.app.candidate_context.common import ContextError, Contract, canonical_hash
from backend.app.candidate_context.configuration import ProjectConfiguration
from backend.app.candidate_context.projects import (
    EvidenceReference,
    ProjectFact,
    ProjectSnapshot,
    contexts,
    make_fact,
    suspicious_text,
)

MAX_SOURCE_FILE_BYTES = 128 * 1024
MAX_SOURCE_TOTAL_BYTES = 768 * 1024
MAX_SOURCE_FILES = 24
MANIFESTS = {
    "package.json",
    "requirements.txt",
    "requirements-runtime.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
}
TECHNOLOGIES = {
    "react": "React",
    "next": "Next.js",
    "typescript": "TypeScript",
    "express": "Express",
    "fastapi": "FastAPI",
    "sqlalchemy": "SQLAlchemy",
    "asyncpg": "PostgreSQL",
    "psycopg": "PostgreSQL",
    "redis": "Redis",
    "bullmq": "BullMQ",
    "prisma": "Prisma",
    "mongoose": "MongoDB",
    "django": "Django",
    "flask": "Flask",
    "celery": "Celery",
    "pydantic": "Pydantic",
    "@supabase/supabase-js": "Supabase",
    "pg": "PostgreSQL",
    "pymongo": "MongoDB",
    "socket.io": "Socket.IO",
    "socket.io-client": "Socket.IO",
    "razorpay": "Razorpay",
    "qdrant-client": "Qdrant",
    "dramatiq": "Dramatiq",
    "langchain": "LangChain",
    "pgvector": "pgvector",
    "pytesseract": "Tesseract OCR",
}


def allowed_path(value: str) -> bool:
    path = PurePosixPath(value)
    if (
        len(value) > 240
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(
            part.startswith(".")
            or part
            in {"node_modules", "vendor", "dist", "secrets", "fixtures"}
            or re.search(r"credential|private|secret|token", part, re.I)
            for part in path.parts
        )
    ):
        return False
    return (
        path.name in MANIFESTS
        or path.name.lower().startswith("readme")
        or (
            path.suffix in {".md", ".sql", ".prisma"}
            and path.parts[0] in {"docs", "schema", "prisma", "migrations"}
        )
        or (
            path.suffix in {".py", ".ts", ".tsx", ".js", ".go", ".java", ".rs"}
            and path.parts[0] in {"src", "app", "apps", "backend", "frontend", "socket-server", "e2e", "tests"}
            and ("tests" not in path.parts or path.name.startswith("test_") or ".test." in path.name or ".spec." in path.name)
        )
    )


class RepositorySnapshot(Contract):
    repository_url: str = Field(max_length=2048)
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: dict[str, Annotated[str, StringConstraints(strip_whitespace=False)]] = Field(max_length=MAX_SOURCE_FILES)

    @model_validator(mode="after")
    def bounded(self):
        ProjectConfiguration.model_validate(
            {
                "id": "project-validation",
                "priority": 1,
                "repository_url": self.repository_url,
            }
        )
        total = 0
        for path, text in self.files.items():
            size = len(text.encode("utf-8"))
            if not allowed_path(path) or size > MAX_SOURCE_FILE_BYTES:
                raise ValueError("unsupported_or_oversized_source_file")
            total += size
        if total > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError("source_snapshot_too_large")
        return self


class RepositoryReader(Protocol):
    async def snapshot(self, project: ProjectConfiguration) -> RepositorySnapshot: ...


class AuthorizedCheckoutReader:
    def __init__(self, checkouts: Mapping[str, Path], *, selected_paths: Mapping[str, tuple[str, ...]] | None = None):
        self.checkouts = {key.rstrip("/"): value for key, value in checkouts.items()}
        self.selected_paths = selected_paths or {}

    async def snapshot(self, project: ProjectConfiguration) -> RepositorySnapshot:
        try:
            async with asyncio.timeout(30):
                return await self._snapshot(project)
        except TimeoutError:
            raise ContextError("repository_read_timeout") from None

    async def _snapshot(self, project: ProjectConfiguration) -> RepositorySnapshot:
        repository = str(project.repository_url or "").rstrip("/")
        root = self.checkouts.get(repository)
        if root is None or root.is_symlink() or not root.is_dir():
            raise ContextError("repository_not_authorized_or_unavailable")
        root = root.resolve()

        async def git(*arguments: str, maximum: int = MAX_SOURCE_FILE_BYTES) -> str:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(root),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={
                    "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                },
            )
            try:
                async with asyncio.timeout(8):
                    output = bytearray()
                    if process.stdout is None:
                        raise ContextError("repository_read_failed_or_too_large")
                    while True:
                        chunk = await process.stdout.read(
                            min(65536, maximum + 1 - len(output))
                        )
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise ContextError("repository_read_failed_or_too_large")
                    await process.wait()
                    if process.returncode:
                        raise ContextError("repository_read_failed_or_too_large")
                    return output.decode("utf-8")
            except (TimeoutError, UnicodeError):
                raise ContextError("repository_read_failed_or_too_large") from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

        origin = (await git("remote", "get-url", "origin")).rstrip("\n")
        normalized = (
            origin.replace("git@github.com:", "https://github.com/")
            .removesuffix(".git")
            .rstrip("/")
        )
        if normalized != repository:
            raise ContextError("repository_origin_mismatch")
        sha = (await git("rev-parse", "HEAD")).rstrip("\n")
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ContextError("repository_revision_invalid")
        listing = await git("ls-tree", "-r", "--long", sha, maximum=1024 * 1024)
        candidates = []
        for entry in listing.splitlines():
            match = re.fullmatch(
                r"(100644|100755) blob ([a-f0-9]{40})\s+(\d+)\t(.+)", entry
            )
            if (
                match
                and allowed_path(match[4])
                and int(match[3]) <= MAX_SOURCE_FILE_BYTES
            ):
                candidates.append((match[4], int(match[3])))
        candidates.sort(
            key=lambda item: (PurePosixPath(item[0]).name not in MANIFESTS, not PurePosixPath(item[0]).name.lower().startswith("readme"), item[0])
        )
        selected = self.selected_paths.get(repository)
        if selected is not None:
            if len(selected) > MAX_SOURCE_FILES or len(set(selected)) != len(selected):
                raise ContextError("invalid_source_selection")
            by_path = dict(candidates)
            if any(path not in by_path for path in selected):
                raise ContextError("unsupported_or_unavailable_source_selection")
            candidates = [(path, by_path[path]) for path in selected]
        files: dict[str, str] = {}
        total = 0
        for path, size in candidates:
            if len(files) >= MAX_SOURCE_FILES or total + size > MAX_SOURCE_TOTAL_BYTES:
                break
            files[path] = await git("show", f"{sha}:{path}")
            total += size
        return RepositorySnapshot(
            repository_url=repository, commit_sha=sha, files=files
        )


def extract_project(
    project: ProjectConfiguration,
    snapshot: RepositorySnapshot,
    *,
    owner_facts: tuple[ProjectFact, ...] = (),
) -> ProjectSnapshot:
    snapshot = RepositorySnapshot.model_validate(snapshot.model_dump())
    if str(project.repository_url or "").rstrip("/") != snapshot.repository_url.rstrip(
        "/"
    ):
        raise ContextError("repository_origin_mismatch")
    facts: list[ProjectFact] = []
    for path, content in sorted(snapshot.files.items()):
        digest = hashlib.sha256(content.encode()).hexdigest()
        ref = EvidenceReference(
            file=path, commit_sha=snapshot.commit_sha, content_sha256=digest
        )
        dependencies: set[str] = set()
        basename = PurePosixPath(path).name
        if basename.startswith("test_") or ".test." in basename or ".spec." in basename:
            facts.append(make_fact(
                "feature", f"The repository contains test source {path}; execution and coverage percentages are not verified.",
                "direct", (ref,),
            ))
            continue
        if basename == "package.json":
            try:
                data = json.loads(content)
                dependencies = set(data.get("dependencies", {})) | set(
                    data.get("devDependencies", {})
                )
            except (ValueError, TypeError, AttributeError):
                dependencies = set()
        elif basename.startswith("requirements"):
            dependencies = {
                match[1].casefold()
                for line in content.splitlines()
                if (
                    match := re.match(
                        r"^([a-zA-Z][\w.-]*)\s*(?:[<=>~!]|$)", line.strip()
                    )
                )
            }
        elif basename == "pyproject.toml":
            import tomllib

            try:
                data = tomllib.loads(content)
                dependencies = {
                    re.split(r"[<=>~!\[; ]", name)[0].casefold()
                    for name in data.get("project", {}).get("dependencies", [])
                }
                dependencies.update(
                    data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                )
            except (ValueError, TypeError, AttributeError):
                dependencies = set()
        for name in sorted(dependencies & TECHNOLOGIES.keys()):
            technology = TECHNOLOGIES[name]
            facts.append(
                make_fact(
                    "technology",
                    f"The repository declares {technology} as a dependency.",
                    "direct",
                    (ref,),
                    technology=technology,
                )
            )
        if basename.lower().startswith("readme"):
            prose = " ".join(
                line
                for line in content.splitlines()
                if line.strip() and not line.startswith(("#", "```", "!", "<"))
            )
            # Repository prose remains inferred, even when it appears reasonable.
            # Suspicious instructions are excluded entirely, including precomputation.
            if prose and not suspicious_text(prose):
                from backend.app.candidate_context.projects import compact

                facts.append(
                    make_fact(
                        "overview",
                        compact(prose, max_words=80, max_characters=1000),
                        "inferred",
                        (ref,),
                    )
                )
        if PurePosixPath(path).suffix in {".py", ".ts", ".tsx", ".js"}:
            for number, line in enumerate(content.splitlines(), 1):
                if PurePosixPath(path).suffix == ".py":
                    match = re.match(
                        r"\s*(?:from|import)\s+([a-zA-Z][\w-]*)(?:[. ,]|$)", line
                    )
                else:
                    match = re.match(
                        r"\s*import\s+(?:.+?\s+from\s+)?['\"]([@\w/-]+)['\"]", line
                    )
                module = match[1].casefold() if match else ""
                if module not in TECHNOLOGIES:
                    continue
                reference = ref.model_copy(
                    update={"line_start": number, "line_end": number}
                )
                technology = TECHNOLOGIES[module]
                facts.append(
                    make_fact(
                        "technology",
                        f"Source code imports {technology}.",
                        "direct",
                        (reference,),
                        technology=technology,
                    )
                )
    if any(
        fact.verification != "owner_supplied" or not fact.evidence
        for fact in owner_facts
    ):
        raise ContextError("owner_fact_provenance_required")
    for fact in owner_facts:
        for ref in fact.evidence:
            if ref.commit_sha is not None:
                content = snapshot.files.get(ref.file)
                if (ref.commit_sha != snapshot.commit_sha or content is None
                    or hashlib.sha256(content.encode()).hexdigest() != ref.content_sha256
                    or ref.line_end > len(content.splitlines())):
                    raise ContextError("project_evidence_changed_reload")
    facts.extend(fact for fact in owner_facts if not suspicious_text(fact.text))
    unique = tuple({fact.id: fact for fact in facts}.values())[:100]
    declared = {
        fact.technology.casefold()
        for fact in unique
        if fact.technology and fact.verification == "direct"
    }
    unsupported = tuple(
        tech for tech in project.tech_stack if tech.casefold() not in declared
    )
    source_hash = canonical_hash(snapshot.files)
    revision = canonical_hash(
        {
            "configuration": project.model_dump(mode="json"),
            "commit_sha": snapshot.commit_sha,
            "source_hash": source_hash,
            "facts": [fact.model_dump(mode="json") for fact in unique],
        }
    )
    return ProjectSnapshot(
        configuration=project,
        commit_sha=snapshot.commit_sha,
        source_hash=source_hash,
        revision=revision,
        facts=unique,
        unsupported_stack_claims=unsupported,
        candidate_contexts=contexts(unique),
        last_verified_version=snapshot.commit_sha,
    )


def extract_document_project(project: ProjectConfiguration, facts: tuple[ProjectFact, ...]) -> ProjectSnapshot:
    """Resume/employment evidence can be reviewed without inventing a repository."""
    if project.repository_url or not facts or len(facts) > 100:
        raise ContextError("document_project_requires_evidenced_facts_without_repository")
    if any(f.verification != "owner_supplied" or not f.evidence or suspicious_text(f.text)
           or any(ref.commit_sha for ref in f.evidence) for f in facts):
        raise ContextError("owner_fact_provenance_required")
    source_hash = canonical_hash([f.model_dump(mode="json") for f in facts])
    revision = canonical_hash({"configuration": project.model_dump(mode="json"), "source_hash": source_hash})
    return ProjectSnapshot(configuration=project, source_hash=source_hash, revision=revision,
                           facts=facts, candidate_contexts=contexts(facts))
