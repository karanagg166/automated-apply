"""PostgresStore candidate profile repository (mixin over PostgresBase)."""

from __future__ import annotations

import json

from backend.app.browser_v2.answers import normalize
from backend.app.browser_v2.store.base import PostgresBase
from backend.app.browser_v2.store.records import (
    PROFILE_KEYS,
    ProfileMissing,
    RevisionConflict,
    validate_preferences,
)


class ProfileRepo(PostgresBase):
    # --- profile ----------------------------------------------------------------------
    async def load_profile(self):
        # to_jsonb(p) tolerates schema drift; identity fields are only used to scrub LLM prompts.
        row = await self.connection.fetchrow(
            "SELECT id, to_jsonb(p)::text AS profile FROM public.candidate_profiles p "
            "WHERE singleton_key='primary'")
        if row is None:
            return {}, []
        data = json.loads(row["profile"])
        profile = {key: data[key] for key in PROFILE_KEYS if key in data}
        profile.setdefault("verified_skills", [])
        profile.setdefault("preferences", {})
        answers = await self.connection.fetch(
            "SELECT question, answer FROM public.application_answer_drafts "
            "WHERE candidate_profile_id=$1 AND review_status='reviewed'", row["id"])
        return profile, [(a["question"], a["answer"]) for a in answers if normalize(a["question"])]

    async def update_preferences(self, changes):
        """Merge validated keys into candidate_profiles.preferences (version-checked, one statement)."""
        for _ in range(3):
            row = await self.connection.fetchrow(
                "SELECT version, preferences::text AS prefs FROM public.candidate_profiles WHERE singleton_key='primary'")
            if row is None:
                raise ProfileMissing("no_candidate_profile")
            merged = validate_preferences(json.loads(row["prefs"] or "{}") | dict(changes))
            updated = await self.connection.fetchrow(
                """UPDATE public.candidate_profiles SET preferences=$1::jsonb, version=version + 1, updated_at=now()
                   WHERE singleton_key='primary' AND version=$2 RETURNING preferences::text AS prefs""",
                json.dumps(merged), row["version"])
            if updated is not None:
                return json.loads(updated["prefs"])
        raise RevisionConflict(-1)
