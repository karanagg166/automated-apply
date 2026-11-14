"""AST-only conservative routing oracle, never service/ORM/settings initialization."""
import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.app.ai.schemas import QuestionType
from backend.app.core.text import normalize, phrase_in
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def constants(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), scope)


def classifier_oracle():
    scope = dict(__name__=__name__, re=re, dataclass=dataclass, QuestionType=QuestionType, normalize=normalize, phrase_in=phrase_in)
    links = "backend/app/services/profile_link_resolver.py"
    constants(links, {"ALIASES"}, scope)
    extract(links, ["resource_types", "is_file_upload"], scope)
    phrases = "backend/app/knowledge/narrative_phrases.py"
    constants(phrases, {"PHRASES"}, scope)
    extract(phrases, ["canonical_question"], scope)
    path = "backend/app/services/application_question_classifier.py"
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in {"QuestionClassification", "ApplicationQuestionClassifier"}]

    class RemoveRuntimeImport(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module != "backend.app.knowledge.narrative_phrases":
                raise ValueError("unexpected_oracle_runtime_import")
            return None

    module = RemoveRuntimeImport().visit(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)
    return scope, scope["ApplicationQuestionClassifier"]()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope, classifier = classifier_oracle()
    base = ["Email", "e-mail", "Phone", "mobile telephone", "Full name", "your name", "years of experience", "years of professional experience", "years of total experience", "experience in years", "total experience", "notice period", "verified skills", "technical skills", "technologies have you used", "technologies you have used", "education", "educational background", "certification", "certifications", "remote work preference", "remote preference", "salary", "minimum salary", "current CTC", "compensation", "pay expectation", "visa", "sponsorship", "authorized to work", "legally authorised", "right to work", "github", "git hub", "Linked In", "resume", "résumé", "cv", "portfolio", "leetcode", "GFG", "kaggle", "upload CV", "choose file", "project", "built", "build", "best work", "impressive thing", "proudest", "accomplishment", "startup", "why startup", "interested in founding", "motivation", "why", "technical", "implemented", "engineering", "API", "APIs", "integrated", "bug", "experience with Rust", "experience using Java", "worked with Rust", "production issue", "about yourself", "introduce yourself", "professional summary", "short bio", "arbitrary unknown", "???", "email²", "email_", "upload² CV", "github\u0301", "github\u11f02"]
    questions = []
    for text in base:
        questions.extend([text, "What is your " + text + "?", "Explain " + text, "Please provide " + text, text + " and salary", text + " with Java", "" + text.upper()])
    for pronoun in ["me", "us"]:
        for article in ["a", "your"]:
            for suffix in ["", " you built", " that you developed", " you implemented", " and claim 100 users"]:
                questions.extend([f"walk {pronoun} through {article} project{suffix}", f"walk {pronoun} through {article} technically challenging project{suffix}"])
    for company in ["company", "role", "position", "opportunity", "startup"]:
        for action in ["attracts", "drew", "draws"]:
            questions.extend([f"What {action} you to this {company}?", f"What {action} you to our {company} and why Rust?"])
    questions.extend(["give us a brief professional introduction", "share your short professional bio", "tell me a little about yourself", "briefly introduce yourself", "what interests you about this company", "what is your motivation for applying here", "describe your technologies used", "technical skills and technologies have you used", "email and phone", "notice period and availability", "github and linkedin", "describe your github project", "challenging github problem", "why¹ startup", "why_ startup"])
    results = [{"question": question, "canonical": scope["canonical_question"](question), "output": asdict(classifier.classify(question))} for question in questions]
    encoded = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    target = ROOT / "rust/agent-runtime/tests/fixtures/question-corpus.json"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("question_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_question_routing_cases:{len(results)}")


if __name__ == "__main__":
    main()
