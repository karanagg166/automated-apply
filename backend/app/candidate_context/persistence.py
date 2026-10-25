"""Injected atomic JSON records and encrypted blobs; no schema changes.

The SQL adapters reuse existing private forced-RLS tables and the caller's
transaction. They do not initialize a database, commit, change privileges, or
obtain credentials. Memory implementations are explicit test/local adapters.
"""

import asyncio
import copy
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from backend.app.candidate_context.common import ContextError

Record = dict[str, Any]


class RecordStore(Protocol):
    async def read(self, key: str) -> Record | None: ...
    async def compare_and_swap(
        self, key: str, expected_revision: int, value: Record
    ) -> None: ...


class BlobStore(Protocol):
    async def put(self, blob_id: str, ciphertext: str, sha256: str) -> None: ...
    async def read(self, blob_id: str) -> str: ...


class Cipher(Protocol):
    def encrypt(self, raw: bytes) -> str: ...
    def decrypt(self, ciphertext: str) -> bytes: ...


class FernetCipher:
    def __init__(self, key: bytes):
        from cryptography.fernet import Fernet

        self._cipher = Fernet(key)

    def encrypt(self, raw: bytes) -> str:
        return self._cipher.encrypt(raw).decode("ascii")

    def decrypt(self, ciphertext: str) -> bytes:
        from cryptography.fernet import InvalidToken

        try:
            return self._cipher.decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, UnicodeError, ValueError):
            raise ContextError(
                "resume_decryption_failed_restore_existing_key"
            ) from None


def validate_key(key: str) -> None:
    if not re.fullmatch(r"[a-z0-9_:-]{1,50}", key):
        raise ContextError("invalid_record_key")


class MemoryRecordStore:
    """Explicit fictional/test storage; never evidence of production persistence."""

    def __init__(self):
        self._values: dict[str, Record] = {}
        self._lock = asyncio.Lock()

    async def read(self, key: str) -> Record | None:
        validate_key(key)
        return copy.deepcopy(self._values.get(key))

    async def compare_and_swap(
        self, key: str, expected_revision: int, value: Record
    ) -> None:
        validate_key(key)
        async with self._lock:
            previous = self._values.get(key)
            actual = previous["revision"] if previous else 0
            if (
                actual != expected_revision
                or value.get("revision") != expected_revision + 1
            ):
                raise ContextError("concurrent_record_change_reload")
            self._values[key] = copy.deepcopy(value)


class MemoryBlobStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def put(self, blob_id: str, ciphertext: str, sha256: str) -> None:
        if blob_id in self.values:
            return  # An immutable version ID is never replaced on retry.
        self.values[blob_id] = ciphertext

    async def read(self, blob_id: str) -> str:
        try:
            return self.values[blob_id]
        except KeyError:
            raise ContextError("encrypted_resume_blob_unavailable") from None


class SQLRecordStore:
    """OwnerPreference JSONB with atomic CAS; online RLS/TLS is the caller's boundary."""

    def __init__(self, session):
        self.session = session

    async def read(self, key: str) -> Record | None:
        from backend.app.dashboard.models import OwnerPreference

        validate_key(key)
        row = await self.session.get(OwnerPreference, key, populate_existing=True)
        return copy.deepcopy(row.value) if row else None

    async def compare_and_swap(
        self, key: str, expected_revision: int, value: Record
    ) -> None:
        from sqlalchemy import update

        from backend.app.dashboard.models import OwnerPreference
        from backend.app.services.discovery_budget import insert_for

        validate_key(key)
        if value.get("revision") != expected_revision + 1:
            raise ContextError("invalid_record_revision")
        if expected_revision == 0:
            result = await self.session.execute(
                insert_for(self.session)(OwnerPreference)
                .values(key=key, value=value)
                .on_conflict_do_nothing(index_elements=["key"])
                .returning(OwnerPreference.key)
            )
            changed = result.scalar_one_or_none() is not None
        else:
            result = await self.session.execute(
                update(OwnerPreference)
                .where(
                    OwnerPreference.key == key,
                    OwnerPreference.value["revision"].as_integer() == expected_revision,
                )
                .values(value=value)
                .execution_options(synchronize_session=False)
            )
            changed = result.rowcount == 1
        if not changed:
            raise ContextError("concurrent_record_change_reload")
        await self.session.flush()


class SQLResumeBlobStore:
    """Reuse private_resumes, preserving encryption keys and existing approved bytes."""

    def __init__(self, session):
        self.session = session

    async def put(self, blob_id: str, ciphertext: str, sha256: str) -> None:
        from uuid import UUID

        from backend.app.dashboard.models import PrivateResume
        from backend.app.services.discovery_budget import insert_for

        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ContextError("invalid_resume_digest")
        await self.session.execute(
            insert_for(self.session)(PrivateResume)
            .values(
                id=UUID(blob_id),
                label="Resume update awaiting review.pdf",
                ciphertext=ciphertext.encode("ascii"),
                sha256=sha256,
                confirmed=False,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        existing = await self.session.get(
            PrivateResume, UUID(blob_id), populate_existing=True
        )
        if not existing or existing.sha256 != sha256:
            raise ContextError("immutable_resume_blob_conflict")

    async def read(self, blob_id: str) -> str:
        from uuid import UUID

        from backend.app.dashboard.models import PrivateResume

        row = await self.session.get(PrivateResume, UUID(blob_id))
        if not row:
            raise ContextError("encrypted_resume_blob_unavailable")
        return row.ciphertext.decode("ascii")


@asynccontextmanager
async def record_transaction(
    store: MemoryRecordStore,
) -> AsyncIterator[MemoryRecordStore]:
    """An explicit test helper; production callers supply session.begin()."""
    yield store
