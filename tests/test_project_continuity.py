"""Fictional history: preservation, account-independent reads and privacy."""

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.project_continuity import CHUNK_BYTES, recover, snapshot, verify


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.codex = self.base / "codex"
        self.codex.mkdir()
        self.destination = self.project / ".local/history"
        self.transcript = self.codex / "sessions/2026/11/15/test.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "fictional", "cwd": str(self.project)}}) + "\n")
        self.connection = sqlite3.connect(self.codex / "state_5.sqlite")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE TABLE threads (id,rollout_path,cwd,title,git_sha,git_branch,created_at,updated_at,archived)")
        self.connection.execute("INSERT INTO threads VALUES (?,?,?,'private title','sha','branch',1,1,0)",
                                ("fictional", str(self.transcript), str(self.project)))
        self.connection.commit()

    def save(self):
        return snapshot(self.project, self.codex, self.destination)

    def test_history_survives_source_disappearance_without_editing_codex(self):
        original = hashlib.sha256((self.codex / "state_5.sqlite").read_bytes()).hexdigest()
        self.assertEqual(self.save()["saved_transcripts"], 1)
        self.assertEqual(hashlib.sha256((self.codex / "state_5.sqlite").read_bytes()).hexdigest(), original)
        self.transcript.unlink()
        self.assertEqual(self.save()["missing_transcripts"], 1)
        self.assertEqual(verify(self.destination)["transcript_references"], 1)
        self.assertEqual(len(list((self.destination / "snapshots").glob("*.json"))), 2)

    def test_append_shares_unchanged_chunks_and_drops_partial_records(self):
        with self.transcript.open("a") as handle:
            for _ in range(3):
                handle.write(json.dumps({"text": "x" * CHUNK_BYTES}) + "\n")
        self.save()
        before = set((self.destination / "objects").iterdir())
        with self.transcript.open("a") as handle:
            handle.write('{"text":"complete"}\n{"unfinished":')
        self.save()
        self.assertEqual(len(set((self.destination / "objects").iterdir()) - before), 1)
        self.assertEqual(verify(self.destination)["transcript_references"], 2)

    def test_idempotent_private_snapshots_exclude_other_projects_and_auth(self):
        self.connection.execute("INSERT INTO threads VALUES ('foreign','/missing','/other','secret','','',1,1,0)")
        self.connection.commit()
        (self.codex / "auth.json").write_text("secret-not-for-backup")
        first, second = self.save(), self.save()
        self.assertEqual(first, second)
        self.assertEqual(first["indexed_threads"], 1)
        for file in self.destination.rglob("*"):
            self.assertEqual(file.stat().st_mode & 0o077, 0)
            if file.is_file():
                self.assertNotIn(b"secret-not-for-backup", file.read_bytes())

    def test_wrong_identity_and_transcript_symlinks_are_refused(self):
        self.transcript.write_text('{"type":"session_meta","payload":{"id":"other"}}\n')
        self.assertEqual(self.save()["unreadable_transcripts"], 1)
        self.transcript.unlink()
        self.transcript.symlink_to(self.codex / "state_5.sqlite")
        self.assertEqual(self.save()["unreadable_transcripts"], 1)

    def test_corruption_is_detected_and_never_silently_overwritten(self):
        self.save()
        file = next((self.destination / "objects").iterdir())
        file.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "snapshot_object_corrupt"):
            verify(self.destination)
        self.assertEqual(self.save()["unreadable_transcripts"], 1)
        self.assertEqual(file.read_bytes(), b"corrupt")

    def test_output_symlink_cannot_redirect_private_backups(self):
        self.destination.parent.mkdir()
        external = self.base / "external"
        external.mkdir()
        os.symlink(external, self.destination)
        with self.assertRaisesRegex(ValueError, "unsafe_snapshot_directory"):
            self.save()
        self.assertEqual(list(external.iterdir()), [])

    def test_recovery_exports_complete_saved_bytes_after_account_index_changes(self):
        original = self.transcript.read_bytes()
        self.save()
        self.transcript.unlink()
        self.connection.execute("DELETE FROM threads")
        self.connection.commit()
        self.save()
        result = recover(self.destination, "fictional")
        self.assertEqual(Path(result["path"]).read_bytes(), original)
        self.assertFalse(result["codex_database_modified"])
        self.assertEqual(Path(result["path"]).stat().st_mode & 0o077, 0)

    def test_missing_transcripts_are_reported_without_fabricating_recovery(self):
        self.transcript.unlink()
        self.save()
        with self.assertRaisesRegex(ValueError, "no_retained_transcript_for_thread"):
            recover(self.destination, "fictional")

    def test_missing_store_cannot_report_a_successful_verification(self):
        with self.assertRaisesRegex(ValueError, "snapshot_store_unavailable"):
            verify(self.destination)

    def test_transcript_path_traversal_is_rejected_before_file_read(self):
        self.connection.execute("UPDATE threads SET rollout_path=?",
                                (str(self.codex / "sessions/../auth.json"),))
        self.connection.commit()
        (self.codex / "auth.json").write_text("secret-not-for-backup")
        self.assertEqual(self.save()["unreadable_transcripts"], 1)
        self.assertEqual(list((self.destination / "objects").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
