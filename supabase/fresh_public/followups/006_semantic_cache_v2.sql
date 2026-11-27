-- Python v2 Phase 4 (2026-11-28): poison-proof semantic cache metadata.
--
-- Requires followup 004 (public.semantic_cache). Additive and idempotent: only ADD COLUMN IF NOT
-- EXISTS, named CHECK constraints added when missing, and CREATE INDEX IF NOT EXISTS. No table,
-- column, row, constraint or grant is altered or dropped, and the (kind, normalized_question)
-- unique key the running code uses for ON CONFLICT is untouched, so the previous release keeps
-- working while this is applied. Existing rows get: status 'active', scope 'global', counters 0,
-- and NULL intent/field type/profile hash (the Python guards classify those on read; a NULL
-- profile hash on a factual entry is treated as stale, never as current).
-- Ownership/ACL: columns inherit the 004 table's owner, RLS policy and job_agent_runtime grants.
-- Never stores secrets, OTPs or full mail bodies.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS field_type TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS intent_bucket TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS entities JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'global';
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS company_slug TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS profile_version_hash TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS invalidation_scope TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS human_override_count INT NOT NULL DEFAULT 0;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS form_validation_error_count INT NOT NULL DEFAULT 0;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS verified_by TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS cache_key TEXT;
ALTER TABLE public.semantic_cache ADD COLUMN IF NOT EXISTS options_hash TEXT;

DO $checks$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_semantic_cache_v2_enums'
                   AND conrelid = 'public.semantic_cache'::regclass) THEN
        ALTER TABLE public.semantic_cache ADD CONSTRAINT ck_semantic_cache_v2_enums CHECK (
            status IN ('active','quarantined','expired')
            AND scope IN ('global','company')
            AND (invalidation_scope IS NULL
                 OR invalidation_scope IN ('factual_profile','behavioral_stable','company_scoped'))
            AND (field_type IS NULL OR field_type IN
                 ('boolean','single_select','multi_select','number','date','short_text','long_text'))
            AND (intent_bucket IS NULL OR intent_bucket ~ '^[a-z][a-z_]{1,39}$'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_semantic_cache_v2_bounds'
                   AND conrelid = 'public.semantic_cache'::regclass) THEN
        ALTER TABLE public.semantic_cache ADD CONSTRAINT ck_semantic_cache_v2_bounds CHECK (
            human_override_count >= 0 AND form_validation_error_count >= 0
            AND jsonb_typeof(entities) = 'object'
            AND (company_slug IS NULL OR company_slug ~ '^[a-z0-9][a-z0-9-]{0,79}$')
            AND (scope = 'global' OR company_slug IS NOT NULL)
            AND (profile_version_hash IS NULL OR profile_version_hash ~ '^[0-9a-f]{64}$')
            AND (cache_key IS NULL OR cache_key ~ '^[0-9a-f]{64}$')
            AND (options_hash IS NULL OR options_hash ~ '^[0-9a-f]{16}$')
            AND (verified_by IS NULL OR length(verified_by) <= 80)
            AND (quarantine_reason IS NULL OR length(quarantine_reason) <= 300));
    END IF;
END
$checks$;

CREATE INDEX IF NOT EXISTS ix_semantic_cache_status_kind ON public.semantic_cache (kind, status);
CREATE INDEX IF NOT EXISTS ix_semantic_cache_cache_key ON public.semantic_cache (cache_key)
    WHERE cache_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_semantic_cache_company ON public.semantic_cache (company_slug)
    WHERE company_slug IS NOT NULL;

COMMIT;
