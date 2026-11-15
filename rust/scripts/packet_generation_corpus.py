"""Explicit-generation field mapping and request DTOs from actual isolated Python definitions."""
import argparse
import asyncio
import json
from pathlib import Path

from rust.scripts.packet_contract_corpus import packet_models
from rust.scripts.packet_fields_corpus import build

ROOT = Path(__file__).resolve().parents[2]


async def generate():
    modes = []
    for rewrite in [False, True]:
        modes.append(dict(rewrite=rewrite, corpus=await build(generate=True, rewrite=rewrite)))
    model = packet_models()["AnswerGenerateInput"]
    inputs = [dict(expected_revision=1)]
    for field, values in dict(expected_revision=[None, False, True, 0, "1.0", 1.5, 2147483646, 2147483647], rewrite=[None, False, True, "yes", " false ", 2], approved_revision=[1], snapshot=[{}], answer=["injected"], provider=["injected"]).items():
        inputs.extend({"expected_revision": 1, field: value} for value in values)
    contracts = []
    for raw in inputs:
        try: result = dict(accepted=True, output=model.model_validate(raw).model_dump(mode="json"))
        except ValueError: result = dict(accepted=False)
        contracts.append(dict(input=raw, **result))
    return dict(modes=modes, contracts=contracts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    data = asyncio.run(generate())
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-generation-corpus.json"
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded: raise SystemExit("packet_generation_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_generation_field_mappings:{sum(len(m['corpus']['cases']) for m in data['modes'])} request_contracts:{len(data['contracts'])}")


if __name__ == "__main__":
    main()
