"""Paired warm matching computation on identical fictional, prevalidated fixtures."""
import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

from rust.scripts.matching_parity import ROOT, cases, evaluate, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    values = list(cases())
    prepared = [prepare(value) for value in values]
    for value in prepared:
        evaluate(value)
    samples = []
    for _ in range(5):
        wall = time.perf_counter()
        cpu = time.process_time()
        for value in prepared:
            evaluate(value)
        samples.append({"wall_ms": (time.perf_counter() - wall) * 1000, "cpu_ms": (time.process_time() - cpu) * 1000})
    response = subprocess.run([str(ROOT / "target/release/examples/match_contract"), "--benchmark"], input=json.dumps(values).encode(), capture_output=True, check=True, timeout=60, cwd=ROOT)
    rust = json.loads(response.stdout)
    result = {"scope": "Actual Mac warm base+discovery calculation and output projection on fictional data; input normalization/validation and process startup excluded; no DB, model or browser", "platform": os.uname().sysname, "architecture": os.uname().machine, "cases_per_sample": len(values), "samples_per_runtime": 5, "samples": {"python": samples, "rust": rust["samples"]}, "median": {name: {metric: round(statistics.median(row[metric] for row in rows), 3) for metric in ("wall_ms", "cpu_ms")} for name, rows in (("python", samples), ("rust", rust["samples"]))}, "gpu": "NOT MEASURED; no inference invoked"}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
