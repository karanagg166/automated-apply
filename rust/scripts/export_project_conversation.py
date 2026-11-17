"""Generate approved-project conversation fixtures in memory only; no configuration or source IO adapters."""
import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path

from backend.app.candidate_context.persistence import MemoryRecordStore
from backend.app.candidate_context.service import CandidateContextService, ConfigurationRecord, ProjectKnowledge
from rust.scripts.project_context_corpus import fixture

ROOT = Path(__file__).resolve().parents[2]


def normalized(records):
    return {
        key: (ConfigurationRecord if key == "candidate_configuration_v1" else ProjectKnowledge)
        .model_validate(value).model_dump(mode="json")
        for key, value in records.items()
    }


async def build():
    base = fixture()
    stale = deepcopy(base)
    stale["candidate_project-01"]["candidate"]["revision"] = "f" * 64
    changed = deepcopy(base)
    changed["candidate_configuration_v1"]["configuration"]["projects"][0]["priority"] = 2
    multiple = deepcopy(base)
    project = deepcopy(base["candidate_configuration_v1"]["configuration"]["projects"][0])
    project.update(id="project-02", name="Cache", priority=2, repository_url="https://github.com/fictional/cache")
    multiple["candidate_configuration_v1"]["configuration"]["projects"].append(project)
    knowledge = deepcopy(base["candidate_project-01"])
    knowledge["candidate"]["configuration"] = project
    knowledge["approved"]["project_id"] = "project-02"
    multiple["candidate_project-02"] = knowledge
    records = [normalized(value) for value in [base, stale, changed, multiple]]
    cases = []
    for index, value in enumerate(records):
        service = CandidateContextService(MemoryRecordStore(value))
        for question in ["Describe my best project", "Tell me about Queue", "Describe Cache", "What APIs did I personally implement?", "What challenge did I solve?", "Explain my design decision", "PostgreSQL", "Describe project architecture"]:
            for rank in [None, 1, 2]:
                for words, characters in [(100, 2000), (5, 20)]:
                    answer = await service.answer(question, project_rank=rank, max_words=words, max_characters=characters)
                    cases.append(dict(records=index, question=question, rank=rank, max_words=words, max_characters=characters, output=answer.model_dump(mode="json")))
    return dict(records=records, cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value = asyncio.run(build())
    target = ROOT / "rust/agent-runtime/tests/fixtures/project-conversation.json"
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.write:
        target.write_text(data)
    elif target.read_text() != data:
        raise SystemExit("project_conversation_contract_changed")
    print(json.dumps(dict(mode="written" if args.write else "matched", cases=len(value["cases"]))))


if __name__ == "__main__":
    main()
