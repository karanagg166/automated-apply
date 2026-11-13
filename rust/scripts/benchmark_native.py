"""Actual process timings against fictional localhost; no owner data or live services."""
import argparse
import http.server
import json
import os
from pathlib import Path
import statistics
import struct
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = "gdjbmkffcpicbpiikcohlmokkmcpipgp"


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        command = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/api/v1/local-agent/chrome"
        assert self.headers["Authorization"] == "Bearer fictional-native-benchmark-only"
        value = {
            "version": 1, "request_id": command["request_id"],
            "ok": True, "capability": "health", "data": {"fixture": True},
        }
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def measure(argv, env, frame):
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        source.write(frame)
        source.seek(0)
        start = time.perf_counter()
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=source, stdout=output, stderr=errors)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        elapsed = time.perf_counter() - start
        assert child.returncode == 0, "fixture_process_failed"
        output.seek(0)
        raw = output.read()
        assert len(raw) >= 4 and struct.unpack("<I", raw[:4])[0] == len(raw) - 4, "invalid_frame"
        result = json.loads(raw[4:])
        assert result.get("ok") is True and result.get("data", {}).get("fixture") is True, "fixture_response_failed"
        return {"wall_ms": elapsed * 1000, "cpu_ms": (usage.ru_utime + usage.ru_stime) * 1000, "rss_kib": usage.ru_maxrss / (1024 if os.uname().sysname == "Darwin" else 1)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 3 <= args.iterations <= 100:
        raise SystemExit("iterations_must_be_3_to_100")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()), "PYTHONPATH": str(ROOT), "LANG": "en_US.UTF-8"}
    payload = json.dumps({"command": "health", "request_id": "00000000-0000-4000-8000-000000000001"}).encode()
    frame = struct.pack("<I", len(payload)) + payload
    try:
        with tempfile.TemporaryDirectory(prefix="rust-native-fictional-") as tmp:
            config = Path(tmp) / "host.env"
            config.write_text(f"ENVIRONMENT=testing\nDATABASE_URL=sqlite+aiosqlite:///:memory:\nSECRET_KEY=fictional-benchmark-only-secret-key-32-chars\nCHROME_EXTENSION_ID={EXTENSION}\nCHROME_NATIVE_MESSAGING_ENABLED=true\nJOB_AGENT_API_TOKEN=fictional-native-benchmark-only\nLOCAL_AGENT_ENDPOINT=http://127.0.0.1:{server.server_port}\n")
            config.chmod(0o600)
            suffix = [str(config), f"chrome-extension://{EXTENSION}/"]
            commands = {
                "python": [str(ROOT / ".venv/bin/python"), "-m", "backend.app.local_agent.native_host", *suffix],
                "rust": [str(ROOT / "target/release/automated-apply-native"), *suffix],
            }
            # Warm filesystem/package caches equally, then alternate execution order.
            for argv in commands.values():
                measure(argv, env, frame)
            samples = {name: [] for name in commands}
            for iteration in range(args.iterations):
                for name in (list(commands) if iteration % 2 == 0 else list(reversed(commands))):
                    samples[name].append(measure(commands[name], env, frame))
            result = {"scope": "Mac process startup + one fictional localhost health exchange; not production acceptance", "iterations_per_runtime": args.iterations, "platform": os.uname().sysname, "architecture": os.uname().machine, "gpu": "NOT MEASURED; no inference or GPU tools invoked", "samples": samples, "median": {name: {metric: round(statistics.median(row[metric] for row in rows), 3) for metric in rows[0]} for name, rows in samples.items()}}
            text = json.dumps(result, indent=2) + "\n"
            if args.output:
                args.output.write_text(text)
            print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
