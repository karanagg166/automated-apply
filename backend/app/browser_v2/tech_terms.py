"""Shared technology vocabulary (deterministic Tier 0 answers + the semantic-cache qualifier guard)."""

from __future__ import annotations

import re

TECH_ALIASES = {
    "golang": "go", "js": "javascript", "ts": "typescript", "reactjs": "react", "react js": "react",
    "nodejs": "node", "node js": "node", "k8s": "kubernetes", "postgresql": "postgres",
    "vuejs": "vue", "vue js": "vue", "nextjs": "next", "next js": "next", "dotnet": "net",
    "amazon web services": "aws", "google cloud": "gcp", "mongo": "mongodb", "springboot": "spring",
    "spring boot": "spring", "py": "python", "tf": "tensorflow", "ml": "machine learning",
    "ai": "artificial intelligence", "nlp": "natural language processing",
}
TECH_TERMS = frozenset({
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "c#", "net", "php", "ruby",
    "rails", "swift", "kotlin", "scala", "perl", "dart", "elixir", "haskell", "matlab", "react",
    "angular", "vue", "svelte", "next", "node", "express", "nestjs", "django", "flask", "fastapi",
    "spring", "laravel", "flutter", "android", "ios", "html", "css", "tailwind", "graphql", "rest",
    "grpc", "sql", "nosql", "mysql", "postgres", "mongodb", "redis", "cassandra", "dynamodb",
    "elasticsearch", "kafka", "rabbitmq", "spark", "hadoop", "airflow", "snowflake", "databricks",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "aws", "azure", "gcp", "linux",
    "git", "selenium", "playwright", "cypress", "jest", "pytest", "tensorflow", "pytorch", "keras",
    "pandas", "numpy", "machine learning", "deep learning", "artificial intelligence",
    "natural language processing", "computer vision", "llm", "langchain", "power bi", "tableau",
    "excel", "salesforce", "sap", "figma", "devops", "microservices", "blockchain", "solidity",
    "unity", "embedded", "c", "r",
})
# Short/ambiguous terms only count when used as a technology ("in Go", "with R").
CONTEXT_ONLY = frozenset({"go", "c", "r", "net", "rest", "next", "express", "unity", "excel", "swift"})
CONTEXT_PREFIX = re.compile(r"\b(?:in|with|using|on|of|and|or|know|knows)\s*$")


def phrase_terms(text: str, vocabulary: frozenset[str], aliases: dict[str, str],
                  context_only: frozenset[str] = frozenset()) -> frozenset[str]:
    found: set[str] = set()
    padded = f" {text} "
    for alias, canonical in aliases.items():
        if f" {alias} " in padded:
            found.add(canonical)
            padded = padded.replace(f" {alias} ", f" {canonical} ")
    for term in vocabulary:
        for match in re.finditer(rf"(?<![a-z0-9+#]){re.escape(term)}(?![a-z0-9+#])", padded):
            if term in context_only and not CONTEXT_PREFIX.search(padded[:match.start()]):
                continue
            found.add(term)
    # Multi-word terms subsume their parts ("delhi ncr" vs "delhi", "navi mumbai" vs "mumbai").
    return frozenset(t for t in found if not any(t != o and f" {t} " in f" {o} " for o in found))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", (text or "").lower())).strip()


def tech_terms(text: str) -> frozenset[str]:
    """Canonical technologies mentioned in `text` ("ReactJS" -> react, "k8s" -> kubernetes)."""
    return phrase_terms(_normalize(text), TECH_TERMS, TECH_ALIASES, CONTEXT_ONLY)


def is_known_tech(phrase: str) -> bool:
    """A bare skill phrase ("Kubernetes", "AWS Lambda") that names a technology."""
    normalized = _normalize(phrase)
    if not normalized or len(normalized.split()) > 4:
        return False
    # Bare phrases have no "in/with" prefix, so test context-only terms directly.
    return bool(phrase_terms(f"with {normalized}", TECH_TERMS, TECH_ALIASES, CONTEXT_ONLY))
