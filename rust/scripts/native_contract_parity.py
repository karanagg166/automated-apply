"""Compare public-contract acceptance using fictional commands and an offline endpoint."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from backend.app.local_agent.contracts import Command
from backend.app.local_agent.native_host import NAUKRI_QUEUE_OPERATIONS, PROFILE_OPERATIONS

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = "gdjbmkffcpicbpiikcohlmokkmcpipgp"


def main():
    cases = [{"command": name} for name in sorted(PROFILE_OPERATIONS | NAUKRI_QUEUE_OPERATIONS | {"health", "inspect_form", "authorize_form"})]
    cases += [
        {"command": "health", "profile_secret": "short"},
        {"command": "health", "work_id": "invalid"},
        {"command": "health", "tab_id": -1},
        {"command": "health", "extra": "forbidden"},
        {"command": "health", "version": 2},
        {"command": "finish_naukri_work", "work_report": {"kind": "needs_input", "reason": "fixture_missing_fact"}},
        {"command": "finish_naukri_work", "work_report": {"kind": "execution_observation", "execution": {"state": "APPLIED"}}},
        {"command": "health", "receipt": {"submitted": True}},
    ]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()), "PYTHONPATH": str(ROOT)}
    with tempfile.TemporaryDirectory(prefix="rust-parity-fictional-") as tmp:
        config = Path(tmp) / "host.env"
        config.write_text(f"CHROME_EXTENSION_ID={EXTENSION}\nCHROME_NATIVE_MESSAGING_ENABLED=true\nJOB_AGENT_API_TOKEN=fictional-contract-parity-only\nLOCAL_AGENT_ENDPOINT=http://127.0.0.1:1\n")
        config.chmod(0o600)
        for index, value in enumerate(cases):
            try:
                Command.model_validate(value)
                expected = True
            except ValueError:
                expected = False
            payload = json.dumps(value).encode()
            result = subprocess.run([str(ROOT / "target/release/automated-apply-native"), str(config), f"chrome-extension://{EXTENSION}/"], input=struct.pack("<I", len(payload)) + payload, capture_output=True, env=env, timeout=10, check=True)
            raw = result.stdout
            assert len(raw) > 4 and struct.unpack("<I", raw[:4])[0] == len(raw) - 4, "parity_invalid_frame"
            response = json.loads(raw[4:])
            accepted = response.get("error_code") == "backend_offline"
            assert accepted == expected, f"parity_case_{index}_failed"
            assert not result.stderr, "native_stderr_not_empty"
    print(json.dumps({"cases": len(cases), "passed": len(cases), "scope": "typed fictional public-schema examples; not exhaustive cross-field/business parity"}))


if __name__ == "__main__":
    main()
