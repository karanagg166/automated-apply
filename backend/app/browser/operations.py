"""One-worker browser command ownership and explicit cancellation fences.

Operation IDs identify server tasks, never browser handles or submission authority.
Durable packet/dispatch intent remains in the existing services and database.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException


@dataclass
class Operation:
    id: str
    kind: str
    revision: int | None
    cancel_requested: bool = False


class BrowserOperations:
    def __init__(self, lock):
        self.lock = lock
        self.active = {}
        self.generations = {}
        self.stopping = {}

    def public(self, packet_id):
        entry = self.active.get(str(packet_id))
        return (
            {
                "id": entry.id,
                "kind": entry.kind,
                "expected_revision": entry.revision,
                "cancel_requested": entry.cancel_requested,
            }
            if entry
            else None
        )

    @asynccontextmanager
    async def run(self, packet_id, kind, revision=None):
        key = str(packet_id)
        generation = self.generations.get(key, 0)
        if key in self.stopping:
            raise HTTPException(
                409, "Browser cancellation is being reconciled; inspect status"
            )
        async with self.lock(packet_id):
            if key in self.stopping or generation != self.generations.get(key, 0):
                raise HTTPException(
                    409, "Queued browser command cancelled; nothing was replayed"
                )
            entry = Operation(uuid4().hex, kind, revision)
            self.active[key] = entry
            try:
                yield entry
            except Exception:
                self.checkpoint(packet_id)
                raise
            else:
                self.checkpoint(packet_id)
            finally:
                if self.active.get(key) is entry:
                    del self.active[key]

    def request_stop(self, packet_id, operation_id, expected_revision, packet_revision):
        key = str(packet_id)
        if key in self.stopping:
            raise HTTPException(
                409, "Cancellation already requested; inspect operation status"
            )
        entry = self.active.get(key)
        if operation_id is not None:
            if (
                not entry
                or entry.id != str(operation_id).replace("-", "")
                or (entry.revision is not None and expected_revision != entry.revision)
            ):
                raise HTTPException(
                    409, "Active operation changed; inspect status before cancelling"
                )
        elif entry:
            raise HTTPException(
                409, "Inspect the active operation ID before cancelling it"
            )
        elif expected_revision != packet_revision:
            raise HTTPException(
                409, "Packet revision changed; reload before cancelling"
            )
        ticket = uuid4().hex
        self.stopping[key] = ticket
        self.generations[key] = self.generations.get(key, 0) + 1
        if entry:
            entry.cancel_requested = True
        return ticket, self.public(packet_id)

    def checkpoint(self, packet_id):
        entry = self.active.get(str(packet_id))
        if entry and entry.cancel_requested:
            raise HTTPException(
                409, "Owner cancelled this browser command; inspect status before continuing"
            )

    def reconciled(self, packet_id, ticket):
        key = str(packet_id)
        if self.stopping.get(key) == ticket:
            del self.stopping[key]
