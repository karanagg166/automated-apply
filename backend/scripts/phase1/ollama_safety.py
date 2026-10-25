"""Live failure, cancellation, concurrency and restart checks with fictional text."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from backend.app.ai.base import ProviderError
from backend.app.ai.provider_factory import create_provider
from backend.scripts.phase1.ollama_evaluate import REDIS_CONTEXT, settings
from backend.scripts.phase1.ollama_runtime import (
    ENDPOINT,
    MODEL,
    SANDBOX,
    PrivateRuntime,
    heavy_lock,
    local_json,
    process_sample,
)

INSTRUCTIONS = {"style_instruction": "concise", "max_characters": 1000, "max_words": 60}
QUESTION = "Explain Redis caching in two sentences."


async def generate(provider):
    return await provider.generate_structured_answer(QUESTION, REDIS_CONTEXT, INSTRUCTIONS)


async def expected_error(config, code):
    try:
        await generate(create_provider(config))
    except ProviderError as error:
        return {"passed": error.code == code, "error": error.code}
    return {"passed": False, "error": "unexpected_success"}


async def unloaded(root_pid):
    """Also check descendants: /api/ps may be empty while a runner is still starting."""
    stable = 0
    for _ in range(100):
        models = await asyncio.to_thread(local_json, "/api/ps")
        processes = await asyncio.to_thread(process_sample, root_pid)
        stable = stable + 1 if not models["models"] and len(processes["pids"]) == 1 else 0
        if stable >= 4:
            return True
        await asyncio.sleep(0.25)
    return False


async def run(directory, model):
    config = settings(OLLAMA_MODEL=model)
    results = {}
    # Fail rather than adopting an already-running daemon before this probe.
    with PrivateRuntime(directory):
        pass
    results["server_unavailable"] = await expected_error(config, "connection_error")
    with PrivateRuntime(directory) as runtime:
        results["version"] = runtime.version
        results["missing_model"] = await expected_error(
            settings(OLLAMA_MODEL="fictional-model-that-is-not-installed:fixture"), "model_unavailable",
        )
        results["timeout"] = await expected_error(settings(OLLAMA_MODEL=model, LLM_TIMEOUT_SECONDS=1), "timeout")
        results["timeout"]["unloaded"] = await unloaded(runtime.process.pid)
        results["timeout"]["passed"] &= results["timeout"]["unloaded"]

        task = asyncio.create_task(generate(create_provider(config)))
        await asyncio.sleep(0.25)
        task.cancel()
        try:
            await task
            cancelled = False
        except asyncio.CancelledError:
            cancelled = True
        results["cancellation"] = {"passed": cancelled and await unloaded(runtime.process.pid)}

        active = maximum = requests = 0
        intervals = []

        async def request_hook(request):
            nonlocal active, maximum, requests
            active += 1
            requests += 1
            maximum = max(maximum, active)
            intervals.append({"event": "start", "time": time.monotonic()})

        async def response_hook(response):
            nonlocal active
            active -= 1
            intervals.append({"event": "end", "time": time.monotonic(), "status": response.status_code})

        async with httpx.AsyncClient(trust_env=False, event_hooks={
            "request": [request_hook], "response": [response_hook],
        }) as client:
            providers = [create_provider(config), create_provider(config)]
            for provider in providers:
                provider.client = client
            responses = await asyncio.gather(*(generate(provider) for provider in providers), return_exceptions=True)
        results["concurrency"] = {
            "passed": maximum == 1 and requests == 2 and all(not isinstance(r, BaseException) for r in responses),
            "max_active": maximum, "requests": requests, "intervals": intervals,
            "errors": [r.code if isinstance(r, ProviderError) else type(r).__name__
                       for r in responses if isinstance(r, BaseException)],
            "unloaded": await unloaded(runtime.process.pid),
        }
        results["concurrency"]["passed"] &= results["concurrency"]["unloaded"]

        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.post(ENDPOINT + "/api/chat", json={
                "model": "qwen2.5:0.5b-cloud", "messages": [{"role": "user", "content": "Fictional test"}],
                "stream": False, "keep_alive": 0,
            })
        results["daemon_cloud_denied"] = {"passed": response.status_code == 403, "status": response.status_code}

    # Restart the actual binary and require a successful real-model response.
    with PrivateRuntime(directory) as restarted:
        try:
            answer = await generate(create_provider(config))
            results["server_restart"] = {
                "passed": bool(answer.content.answer) and await unloaded(restarted.process.pid),
                "schema_valid": True,
            }
        except ProviderError as error:
            results["server_restart"] = {"passed": False, "error": error.code}

    process = await asyncio.create_subprocess_exec(
        "/usr/bin/sandbox-exec", "-p", SANDBOX, "/usr/bin/curl", "--noproxy", "*",
        "--silent", "--show-error", "--max-time", "2", "https://1.1.1.1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
    results["sandbox_external_network_denied"] = {
        "passed": process.returncode == 7, "exit_code": process.returncode,
        "stderr": stderr.decode(),
    }
    results["unavailable_after_shutdown"] = await expected_error(config, "connection_error")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=[MODEL, "qwen2.5:0.5b"], default=MODEL)
    args = parser.parse_args()
    with heavy_lock():
        results = asyncio.run(run(args.runtime_directory, args.model))
        args.output.write_text(json.dumps(results, indent=2) + "\n")
        args.output.chmod(0o600)
        print(json.dumps(results, indent=2))
        return 0 if all(row["passed"] for row in results.values() if isinstance(row, dict)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
