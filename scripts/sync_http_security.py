"""Generate package-local HTTP policy copies for independent frontend/backend builds."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "contracts/http-security.json"
TARGETS = (
    ROOT / "backend/app/core/http-security.generated.json",
    ROOT / "frontend/src/lib/http-security.generated.json",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    policy = json.loads(SOURCE.read_text())
    if policy["schema_version"] != 1:
        raise SystemExit("unsupported_http_policy_version")
    for pattern in policy["owner_approval"]:
        re.compile(pattern)
    for route in policy["gateway_routes"]:
        re.compile(route["pattern"])
    encoded = SOURCE.read_text()
    for target in TARGETS:
        if args.check:
            if not target.is_file() or target.read_text() != encoded:
                raise SystemExit(f"http_policy_drift:{target.relative_to(ROOT)}")
        else:
            target.write_text(encoded)
    print("http_security_policy_current")


if __name__ == "__main__":
    main()
