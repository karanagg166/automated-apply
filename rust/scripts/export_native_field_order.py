"""Freeze native Pydantic declaration order by reading AST only; no app/settings imports."""

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "rust/agent-runtime/schemas/native-command-field-order.json"
SOURCES = (
    "backend/app/local_agent/contracts.py",
    "backend/app/browser/contracts.py",
    "backend/app/local_agent/intents.py",
    "backend/app/execution/queue_contracts.py",
)


def render():
    schema = json.loads((ROOT / "rust/native-host/schemas/command.json").read_text())
    names = {"Command", *schema.get("$defs", {})}
    order = {}
    for source in SOURCES:
        for node in ast.parse((ROOT / source).read_text()).body:
            if not isinstance(node, ast.ClassDef) or node.name not in names:
                continue
            fields = [
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id != "model_config"
            ]
            definition = (
                schema if node.name == "Command" else schema["$defs"][node.name]
            )
            if node.name in order or set(fields) != set(definition["properties"]):
                raise ValueError("native_field_schema_requires_review")
            order[node.name] = fields
    if set(order) != names:
        raise ValueError("native_field_models_require_review")
    return json.dumps(order, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    result = render()
    if arguments.write:
        OUTPUT.write_text(result)
    elif not OUTPUT.is_file() or OUTPUT.read_text() != result:
        raise SystemExit("native_field_order_drift")


if __name__ == "__main__":
    main()
