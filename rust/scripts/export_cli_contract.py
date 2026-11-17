"""Freeze the known AGY profile literals without importing application configuration."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def assignment(path, name):
    tree = ast.parse((ROOT / path).read_text())
    return next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def profile():
    instruction = ast.literal_eval(assignment("backend/app/ai/prompts.py", "SYSTEM_INSTRUCTION"))
    value = assignment("backend/app/ai/providers/agy.py", "AGENT")
    if not (
        isinstance(value, ast.BinOp)
        and isinstance(value.op, ast.Add)
        and isinstance(value.right, ast.Name)
        and value.right.id == "SYSTEM_INSTRUCTION"
    ):
        raise SystemExit("cli_profile_literal_shape_changed")
    return (ast.literal_eval(value.left) + instruction).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    output = ROOT / "rust/agent-runtime/schemas/agy-agent.md"
    expected = profile()
    if args.write:
        output.write_bytes(expected)
    elif output.read_bytes() != expected:
        raise SystemExit("frozen_cli_profile_differs_from_legacy")
    print(json.dumps({"mode": "written" if args.write else "matched", "profile_sha256": hashlib.sha256(expected).hexdigest()}))


if __name__ == "__main__":
    main()
