"""Owned bounded worker lifecycle, including cancellation during process creation."""

import asyncio
import json
import sys
from contextlib import suppress
from pathlib import Path


class SourceFetch:
    def __init__(self):
        self.sealed = False
        self.processes, self.births, self.cleanup = set(), set(), set()

    def seal(self):
        self.sealed = True
        for process in list(self.processes):
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()

    async def reap(self, birth):
        try:
            process = await asyncio.shield(birth)
            self.processes.add(process)
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.wait()
            self.processes.discard(process)
        except (OSError, ProcessLookupError):
            pass
        finally:
            self.births.discard(birth)

    async def close(self):
        self.seal()
        await asyncio.gather(*(asyncio.shield(t) for t in list(self.cleanup)))
        await asyncio.gather(*(self.reap(t) for t in list(self.births)))

    async def fetch(self, payload):
        if self.sealed:
            raise ValueError("Source reader closed")
        birth = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).with_name("company_source_worker.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
            )
        )
        self.births.add(birth)
        process = None
        try:
            async with asyncio.timeout(15):
                process = await asyncio.shield(birth)
                self.processes.add(process)
                if self.sealed:
                    raise ValueError("Source reader closed")
                output, _ = await process.communicate(json.dumps(payload).encode())
                if self.sealed or process.returncode or len(output) > 32768:
                    raise ValueError("Source reader unavailable")
                result = json.loads(output)
                if (
                    result.get("error")
                    or not isinstance(result.get("company_text"), str)
                    or not 1 <= len(result["company_text"]) <= 4000
                ):
                    raise ValueError("Source reader unavailable")
                return result
        finally:
            task = asyncio.create_task(self.reap(birth))
            self.cleanup.add(task)
            task.add_done_callback(self.cleanup.discard)
            await asyncio.shield(task)
