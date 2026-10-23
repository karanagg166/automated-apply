"""Bounded asset admission and subprocess cleanup; no browser credentials forwarded."""

import asyncio
import base64
import json
import sys
from contextlib import suppress
from pathlib import Path

from backend.app.browser.asset_policy import (
    MAX_ASSET_BYTES,
    MAX_PARALLEL,
    MAX_REQUESTS,
    MAX_TOTAL_BYTES,
    MIMES,
    RESPONSE_HEADERS,
    asset_target,
)

FETCH_TIMEOUT = 10


class AssetUnavailable(Exception):
    pass


class PublicAssets:
    def __init__(self, pins, *, testing=False):
        self.pins, self.testing = pins, testing
        self.sealed = False
        self.requests = self.bytes = self.blocked = 0
        self.processes, self.inflight = set(), set()
        self.slots = asyncio.Semaphore(MAX_PARALLEL)

    def seal(self):
        self.sealed = True
        for process in list(self.processes):
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()

    async def close(self):
        self.seal()
        await asyncio.gather(*(event.wait() for event in list(self.inflight)))

    def state(self):
        return {
            "sealed": self.sealed,
            "requests": self.requests,
            "bytes": self.bytes,
            "blocked": self.blocked,
            "pending": len(self.inflight),
        }

    async def fetch(self, url, kind, origin=None):
        self.requests += 1
        try:
            base, _ = asset_target(url, kind, testing=self.testing)
            if (
                self.sealed
                or base not in self.pins
                or self.requests > MAX_REQUESTS
                or self.bytes >= MAX_TOTAL_BYTES
            ):
                raise AssetUnavailable()
            async with self.slots:
                if self.sealed:
                    raise AssetUnavailable()
                event, process = asyncio.Event(), None
                self.inflight.add(event)
                try:
                    process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        str(Path(__file__).with_name("asset_worker.py")),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        env={"PATH": "/usr/bin:/bin"},
                    )
                    self.processes.add(process)
                    if self.sealed:
                        raise AssetUnavailable()
                    payload = {
                        "url": url,
                        "kind": kind,
                        "address": self.pins[base][0],
                        "testing": self.testing,
                        "origin": origin,
                    }
                    output, _ = await asyncio.wait_for(
                        process.communicate(json.dumps(payload).encode()),
                        timeout=FETCH_TIMEOUT,
                    )
                    if (
                        self.sealed
                        or process.returncode
                        or len(output) > 6 * 1024 * 1024
                    ):
                        raise AssetUnavailable()
                    result = json.loads(output)
                    raw = base64.b64decode(result["body"], validate=True)
                    headers = result["headers"]
                    if not isinstance(headers, dict) or any(
                        key not in RESPONSE_HEADERS
                        or not isinstance(value, str)
                        or len(value) > 4096
                        or any(ord(c) < 32 or ord(c) == 127 for c in value)
                        for key, value in headers.items()
                    ):
                        raise AssetUnavailable()
                    if (
                        len(raw) > MAX_ASSET_BYTES
                        or headers.get("content-type", "").split(";")[0].lower().strip()
                        not in MIMES[kind]
                        or self.bytes + len(raw) > MAX_TOTAL_BYTES
                    ):
                        raise AssetUnavailable()
                    self.bytes += len(raw)
                    return raw, headers
                finally:
                    if process is not None:
                        if process.returncode is None:
                            with suppress(ProcessLookupError):
                                process.kill()
                        await process.wait()
                        self.processes.discard(process)
                    event.set()
                    self.inflight.discard(event)
        except (
            AssetUnavailable,
            ValueError,
            KeyError,
            TypeError,
            OSError,
            TimeoutError,
        ):
            self.blocked += 1
            raise AssetUnavailable() from None
