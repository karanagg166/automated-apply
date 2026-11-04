-- Exact reviewed Naukri worker schema extension; separate online DDL approval required.

-- Preserve existing rows, all grants/RLS, append-only history and original bundle.

BEGIN;

SET LOCAL lock_timeout = '2s';

SET LOCAL statement_timeout = '30s';

LOCK TABLE public.application_packets, public.application_events, public.application_submission_evidence IN ACCESS EXCLUSIVE MODE;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_packets' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_packets_lifecycle_state_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((lifecycle_state)::text = ANY ((ARRAY['created'::character varying, 'preparing'::character varying, 'needs_input'::character varying, 'ready_for_review'::character varying, 'reviewed'::character varying, 'approved_for_manual_handoff'::character varying, 'external_application_opened'::character varying, 'user_reported_submitted'::character varying, 'provider_confirmed_submitted'::character varying, 'withdrawn'::character varying, 'abandoned'::character varying])::text[])))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_packets' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_packets_tracking_state_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((tracking_state)::text = ANY ((ARRAY['not_applied'::character varying, 'applied_manually'::character varying, 'application_incomplete'::character varying, 'application_rejected'::character varying, 'interview_scheduled'::character varying, 'offer_received'::character varying, 'archived'::character varying])::text[])))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_packets' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_packets_readiness_state_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((readiness_state)::text = ANY ((ARRAY['needs_profile'::character varying, 'needs_input'::character varying, 'needs_resume'::character varying, 'needs_review'::character varying, 'ready_for_manual_handoff'::character varying, 'manual_action_required'::character varying, 'completed_by_user'::character varying, 'unsupported'::character varying])::text[])))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_events' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_events_event_type_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((event_type)::text = ANY ((ARRAY['packet_created'::character varying, 'packet_refreshed'::character varying, 'questions_added'::character varying, 'answer_generated'::character varying, 'answer_edited'::character varying, 'packet_reviewed'::character varying, 'packet_approved'::character varying, 'tracking_updated'::character varying, 'user_reported_submission'::character varying])::text[])))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_events' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_events_origin_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((origin)::text = ANY ((ARRAY['owner_rest'::character varying, 'system'::character varying])::text[])))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_submission_evidence' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_submission_evidence_confirmation_source_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((confirmation_source)::text = 'user_reported'::text))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_submission_evidence' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_submission_evidence_evidence_confidence_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (((evidence_confidence)::text = 'self_reported_unverified'::text))$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname='application_submission_evidence' AND pg_get_userbyid(t.relowner)='job_agent_owner' AND c.conname='application_submission_evidence_human_confirmed_check' AND c.convalidated AND pg_get_constraintdef(c.oid)=$expected$CHECK (human_confirmed)$expected$) THEN RAISE EXCEPTION 'reviewed_naukri_constraint_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF pg_get_functiondef('public.application_packet_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.application_packet_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE material_changed boolean;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application packets retain audit history'; END IF;
    IF NEW.lifecycle_state='provider_confirmed_submitted' THEN
        RAISE EXCEPTION 'No authorized submission provider exists in Phase 5A';
    END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.lifecycle_state<>'created' OR NEW.revision<>1 OR NEW.approved_revision IS NOT NULL OR NEW.tracking_state<>'not_applied' THEN
            RAISE EXCEPTION 'Application packets start as unsubmitted drafts';
        END IF;
    ELSE
        IF (NEW.id,NEW.job_id,NEW.candidate_profile_id,NEW.idempotency_key,NEW.request_hash,NEW.created_at)
           IS DISTINCT FROM (OLD.id,OLD.job_id,OLD.candidate_profile_id,OLD.idempotency_key,OLD.request_hash,OLD.created_at) THEN
            RAISE EXCEPTION 'Application identity is immutable';
        END IF;
        material_changed := (NEW.snapshot,NEW.resume_resource_id,NEW.application_url,NEW.candidate_profile_version,NEW.platform)
           IS DISTINCT FROM (OLD.snapshot,OLD.resume_resource_id,OLD.application_url,OLD.candidate_profile_version,OLD.platform);
        IF material_changed THEN
            NEW.approved_revision := NULL;
            IF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
                NEW.lifecycle_state := 'needs_input'; NEW.readiness_state := 'needs_review';
            END IF;
            IF NEW.revision=OLD.revision AND OLD.lifecycle_state<>'preparing' THEN NEW.revision:=OLD.revision+1; END IF;
        END IF;
        IF NEW.revision<OLD.revision OR NEW.revision>OLD.revision+1 THEN RAISE EXCEPTION 'Invalid application revision'; END IF;
        IF OLD.lifecycle_state IN ('user_reported_submitted','withdrawn','abandoned') AND material_changed THEN
            RAISE EXCEPTION 'Closed application content is immutable';
        END IF;
        IF OLD.lifecycle_state IN ('withdrawn','abandoned') AND NEW.lifecycle_state<>OLD.lifecycle_state THEN
            RAISE EXCEPTION 'Closed application cannot reopen';
        END IF;
        IF OLD.lifecycle_state='user_reported_submitted' AND NEW.lifecycle_state NOT IN ('user_reported_submitted','withdrawn') THEN
            RAISE EXCEPTION 'Submission history cannot be erased';
        END IF;
        IF NEW.lifecycle_state='external_application_opened' AND OLD.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') THEN
            RAISE EXCEPTION 'Opening requires approval';
        END IF;
        NEW.updated_at:=clock_timestamp();
    END IF;
    IF NEW.lifecycle_state='user_reported_submitted' AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id AND e.human_confirmed
    ) THEN RAISE EXCEPTION 'Manual submission requires explicit self-reported evidence'; END IF;
    IF NEW.tracking_state IN ('applied_manually','application_rejected','interview_scheduled','offer_received') AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id
    ) THEN RAISE EXCEPTION 'Post-submission tracking requires evidence'; END IF;
    IF NEW.approved_revision IS NOT NULL THEN
        IF NEW.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') OR NEW.approved_revision<>NEW.revision
           OR NEW.candidate_profile_version<>(SELECT version FROM public.candidate_profiles WHERE id=NEW.candidate_profile_id)
           OR NEW.application_url IS NULL OR NEW.resume_resource_id IS NULL
           OR NEW.snapshot->'destination'->>'valid' IS DISTINCT FROM 'true'
           OR NEW.snapshot->'destination'->>'source_confidence' IS DISTINCT FROM 'source_consistent'
           OR NEW.application_url IS DISTINCT FROM NEW.snapshot->'destination'->>'application_url'
           OR NEW.resume_resource_id::text IS DISTINCT FROM NEW.snapshot->'resume'->'selected'->>'resource_id'
           OR NOT EXISTS (SELECT 1 FROM public.candidate_resources r WHERE r.id=NEW.resume_resource_id
                          AND r.candidate_profile_id=NEW.candidate_profile_id AND r.user_confirmed AND r.resource_type='resume'
                          AND r.url=NEW.snapshot->'resume'->'selected'->>'url')
           OR EXISTS (SELECT 1 FROM public.application_packet_fields f WHERE f.packet_id=NEW.id AND
                ((f.required AND f.validation_status<>'file_upload_required' AND
                 (COALESCE(f.human_answer,f.proposed_answer) IS NULL OR f.validation_status<>'draft_ready'))
                OR (COALESCE(f.human_answer,f.proposed_answer) IS NOT NULL AND f.requires_review AND f.review_status<>'reviewed'))) THEN
            RAISE EXCEPTION 'Approval requires current profile, resume, destination and reviewed answers';
        END IF;
    ELSIF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
        RAISE EXCEPTION 'Handoff requires revision approval';
    END IF;
    RETURN NEW;
END;
$function$
$expected$ THEN RAISE EXCEPTION 'reviewed_naukri_function_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF pg_get_functiondef('public.application_field_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.application_field_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE p public.application_packets;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application fields retain audit history'; END IF;
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF p.lifecycle_state IN ('user_reported_submitted','withdrawn','abandoned') THEN RAISE EXCEPTION 'Closed application fields are immutable'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (NEW.id,NEW.packet_id,NEW.position,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.packet_id,OLD.position,OLD.created_at) THEN
            RAISE EXCEPTION 'Application field identity is immutable';
        END IF;
        IF p.lifecycle_state<>'preparing' THEN
            UPDATE public.application_packets SET revision=revision+1,approved_revision=NULL,lifecycle_state='needs_input',readiness_state='needs_review' WHERE id=NEW.packet_id;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['answer_revision','review_status','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['answer_revision','review_status','updated_at']) THEN
            NEW.answer_revision:=OLD.answer_revision+1; NEW.review_status:='pending';
        END IF;
        NEW.updated_at:=clock_timestamp();
    ELSIF p.approved_revision IS NOT NULL THEN RAISE EXCEPTION 'Invalidate approval before adding fields'; END IF;
    RETURN NEW;
END;
$function$
$expected$ THEN RAISE EXCEPTION 'reviewed_naukri_function_required_no_reapply'; END IF; END $pre$;

DO $pre$ BEGIN IF pg_get_functiondef('public.application_history_guard()'::regprocedure) IS DISTINCT FROM $expected$CREATE OR REPLACE FUNCTION public.application_history_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE p public.application_packets;
BEGIN
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF NEW.packet_revision<>p.revision THEN RAISE EXCEPTION 'History must reference the current packet revision'; END IF;
    IF TG_TABLE_NAME='application_events' THEN
        IF NEW.next_state<>p.lifecycle_state THEN RAISE EXCEPTION 'Event state must match packet'; END IF;
        IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.application_submission_evidence e WHERE e.id=NEW.evidence_id AND e.packet_id=NEW.packet_id
        ) THEN RAISE EXCEPTION 'Evidence belongs to a different application'; END IF;
    ELSIF p.lifecycle_state<>'preparing' THEN RAISE EXCEPTION 'Submission evidence requires an explicit revision claim'; END IF;
    RETURN NEW;
END;
$function$
$expected$ THEN RAISE EXCEPTION 'reviewed_naukri_function_required_no_reapply'; END IF; END $pre$;

ALTER TABLE public.application_packets DROP CONSTRAINT application_packets_lifecycle_state_check, ADD CONSTRAINT application_packets_lifecycle_state_check CHECK (lifecycle_state IN ('created','preparing','needs_input','ready_for_review','reviewed','approved_for_manual_handoff','external_application_opened','user_reported_submitted','provider_confirmed_submitted','withdrawn','abandoned','submitting','submission_unknown'));

ALTER TABLE public.application_packets DROP CONSTRAINT application_packets_tracking_state_check, ADD CONSTRAINT application_packets_tracking_state_check CHECK (tracking_state IN ('not_applied','applied_manually','application_incomplete','application_rejected','interview_scheduled','offer_received','archived','applied_verified'));

ALTER TABLE public.application_packets DROP CONSTRAINT application_packets_readiness_state_check, ADD CONSTRAINT application_packets_readiness_state_check CHECK (readiness_state IN ('needs_profile','needs_input','needs_resume','needs_review','ready_for_manual_handoff','manual_action_required','completed_by_user','unsupported','completed_verified'));

ALTER TABLE public.application_events DROP CONSTRAINT application_events_event_type_check, ADD CONSTRAINT application_events_event_type_check CHECK (event_type IN ('packet_created','packet_refreshed','questions_added','answer_generated','answer_edited','packet_reviewed','packet_approved','tracking_updated','user_reported_submission','naukri_apply_admitted','naukri_persistent_ui_confirmed'));

ALTER TABLE public.application_events DROP CONSTRAINT application_events_origin_check, ADD CONSTRAINT application_events_origin_check CHECK (origin IN ('owner_rest','system','local_worker'));

ALTER TABLE public.application_submission_evidence DROP CONSTRAINT application_submission_evidence_confirmation_source_check, ADD CONSTRAINT application_submission_evidence_confirmation_source_check CHECK (confirmation_source IN ('user_reported','naukri_status_ui'));

ALTER TABLE public.application_submission_evidence DROP CONSTRAINT application_submission_evidence_evidence_confidence_check, ADD CONSTRAINT application_submission_evidence_evidence_confidence_check CHECK (evidence_confidence IN ('self_reported_unverified','provider_ui_persistent'));

ALTER TABLE public.application_submission_evidence DROP CONSTRAINT application_submission_evidence_human_confirmed_check, ADD CONSTRAINT application_submission_evidence_human_confirmed_check CHECK ((confirmation_source='user_reported' AND evidence_confidence='self_reported_unverified' AND human_confirmed) OR (confirmation_source='naukri_status_ui' AND evidence_confidence='provider_ui_persistent' AND NOT human_confirmed AND receipt_reference IS NOT NULL AND receipt_reference ~ '^naukri_worker_receipt:[0-9]{10,20}$'));

CREATE OR REPLACE FUNCTION public.application_packet_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE material_changed boolean;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application packets retain audit history'; END IF;
    IF NEW.lifecycle_state IN ('submitting','submission_unknown','provider_confirmed_submitted') THEN
        IF NEW.platform<>'naukri' OR NOT EXISTS (
            SELECT 1 FROM public.owner_preferences w
            WHERE w.key='apply_work:'||(w.value->>'id') AND w.value->>'platform'='naukri'
              AND w.value->>'packet_id'=NEW.id::text AND w.value->>'job_id'=NEW.job_id::text
              AND w.value->>'candidate_profile_id'=NEW.candidate_profile_id::text
              AND w.value->>'profile_version'=NEW.candidate_profile_version::text
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.value->'admitted_actions') a
                          WHERE a->>'fingerprint' LIKE 'apply:%')
              AND (NEW.lifecycle_state='provider_confirmed_submitted' OR
                   w.value->>'packet_revision'=NEW.revision::text)
        ) THEN RAISE EXCEPTION 'Naukri execution requires exact durable Apply admission'; END IF;
    END IF;
    IF NEW.lifecycle_state='provider_confirmed_submitted' OR NEW.tracking_state='applied_verified'
       OR NEW.readiness_state='completed_verified' THEN
        IF NEW.lifecycle_state<>'provider_confirmed_submitted' OR NEW.tracking_state<>'applied_verified'
           OR NEW.readiness_state<>'completed_verified' OR NOT EXISTS (
            SELECT 1 FROM public.application_submission_evidence e
            JOIN public.owner_preferences r ON r.key=e.receipt_reference
            JOIN public.owner_preferences w ON w.key='apply_work:'||(r.value->>'queue_id')
            WHERE e.packet_id=NEW.id AND e.packet_revision=NEW.revision
              AND e.confirmation_source='naukri_status_ui' AND e.evidence_confidence='provider_ui_persistent'
              AND NOT e.human_confirmed AND r.key='naukri_worker_receipt:'||(r.value->>'requisition')
              AND r.value->>'status'='Application Sent'
              AND r.value->>'confirmation_source'='naukri_application_status_ui'
              AND r.value->>'operation_mode'='recurring_worker_ui'
              AND r.value->>'persistent_after_reload'='true' AND r.value->>'worker_dispatched'='true'
              AND r.value->>'account_sha256' ~ '^[a-f0-9]{64}$'
              AND r.value->'second_observation'->>'account_sha256'=r.value->>'account_sha256'
              AND r.value->'second_observation'->>'state'='APPLICATION_SENT'
              AND r.value->'first_observation'->>'document_id' IS NOT NULL
              AND r.value->'first_observation'->>'document_id'<>r.value->'second_observation'->>'document_id'
              AND r.value->'first_observation'->>'evidence_sha256' ~ '^[a-f0-9]{64}$'
              AND r.value->'second_observation'->>'evidence_sha256' ~ '^[a-f0-9]{64}$'
              AND (r.value->'first_observation'->>'observed_at')::timestamptz<(r.value->>'observed_at')::timestamptz
              AND (r.value->>'observed_at')::timestamptz<=clock_timestamp()+interval '5 minutes'
              AND w.value->>'packet_id'=NEW.id::text AND w.value->>'job_id'=NEW.job_id::text
              AND w.value->>'candidate_profile_id'=NEW.candidate_profile_id::text
              AND w.value->>'account_sha256'=r.value->>'account_sha256'
              AND w.value->>'requisition'=r.value->>'requisition'
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.value->'admitted_actions') a
                          WHERE a->>'fingerprint' LIKE 'apply:%')
        ) THEN RAISE EXCEPTION 'Naukri confirmation requires independently persistent worker evidence'; END IF;
    END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.lifecycle_state<>'created' OR NEW.revision<>1 OR NEW.approved_revision IS NOT NULL OR NEW.tracking_state<>'not_applied' THEN
            RAISE EXCEPTION 'Application packets start as unsubmitted drafts';
        END IF;
    ELSE
        IF (NEW.id,NEW.job_id,NEW.candidate_profile_id,NEW.idempotency_key,NEW.request_hash,NEW.created_at)
           IS DISTINCT FROM (OLD.id,OLD.job_id,OLD.candidate_profile_id,OLD.idempotency_key,OLD.request_hash,OLD.created_at) THEN
            RAISE EXCEPTION 'Application identity is immutable';
        END IF;
        material_changed := (NEW.snapshot,NEW.resume_resource_id,NEW.application_url,NEW.candidate_profile_version,NEW.platform)
           IS DISTINCT FROM (OLD.snapshot,OLD.resume_resource_id,OLD.application_url,OLD.candidate_profile_version,OLD.platform);
        IF material_changed THEN
            NEW.approved_revision := NULL;
            IF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
                NEW.lifecycle_state := 'needs_input'; NEW.readiness_state := 'needs_review';
            END IF;
            IF NEW.revision=OLD.revision AND OLD.lifecycle_state<>'preparing' THEN NEW.revision:=OLD.revision+1; END IF;
        END IF;
        IF NEW.revision<OLD.revision OR NEW.revision>OLD.revision+1 THEN RAISE EXCEPTION 'Invalid application revision'; END IF;
        IF OLD.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown','withdrawn','abandoned') AND material_changed THEN
            RAISE EXCEPTION 'Closed application content is immutable';
        END IF;
        IF OLD.lifecycle_state IN ('withdrawn','abandoned') AND NEW.lifecycle_state<>OLD.lifecycle_state THEN
            RAISE EXCEPTION 'Closed application cannot reopen';
        END IF;
        IF OLD.lifecycle_state='user_reported_submitted' AND NEW.lifecycle_state NOT IN ('user_reported_submitted','withdrawn') THEN
            RAISE EXCEPTION 'Submission history cannot be erased';
        END IF;
        IF NEW.lifecycle_state='external_application_opened' AND OLD.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') THEN
            RAISE EXCEPTION 'Opening requires approval';
        END IF;
        IF OLD.lifecycle_state='provider_confirmed_submitted' AND NEW.lifecycle_state<>'provider_confirmed_submitted' THEN
            RAISE EXCEPTION 'Verified Naukri submission history cannot be erased';
        END IF;
        IF OLD.lifecycle_state IN ('submitting','submission_unknown')
           AND NEW.lifecycle_state NOT IN ('submitting','submission_unknown','provider_confirmed_submitted') THEN
            RAISE EXCEPTION 'Uncertain Naukri submission cannot be reopened';
        END IF;
        NEW.updated_at:=clock_timestamp();
    END IF;
    IF NEW.lifecycle_state='user_reported_submitted' AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id AND e.human_confirmed
    ) THEN RAISE EXCEPTION 'Manual submission requires explicit self-reported evidence'; END IF;
    IF NEW.tracking_state IN ('applied_manually','application_rejected','interview_scheduled','offer_received') AND NOT EXISTS (
        SELECT 1 FROM public.application_submission_evidence e WHERE e.packet_id=NEW.id
    ) THEN RAISE EXCEPTION 'Post-submission tracking requires evidence'; END IF;
    IF NEW.approved_revision IS NOT NULL THEN
        IF NEW.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') OR NEW.approved_revision<>NEW.revision
           OR NEW.candidate_profile_version<>(SELECT version FROM public.candidate_profiles WHERE id=NEW.candidate_profile_id)
           OR NEW.application_url IS NULL OR NEW.resume_resource_id IS NULL
           OR NEW.snapshot->'destination'->>'valid' IS DISTINCT FROM 'true'
           OR NEW.snapshot->'destination'->>'source_confidence' IS DISTINCT FROM 'source_consistent'
           OR NEW.application_url IS DISTINCT FROM NEW.snapshot->'destination'->>'application_url'
           OR NEW.resume_resource_id::text IS DISTINCT FROM NEW.snapshot->'resume'->'selected'->>'resource_id'
           OR NOT EXISTS (SELECT 1 FROM public.candidate_resources r WHERE r.id=NEW.resume_resource_id
                          AND r.candidate_profile_id=NEW.candidate_profile_id AND r.user_confirmed AND r.resource_type='resume'
                          AND r.url=NEW.snapshot->'resume'->'selected'->>'url')
           OR EXISTS (SELECT 1 FROM public.application_packet_fields f WHERE f.packet_id=NEW.id AND
                ((f.required AND f.validation_status<>'file_upload_required' AND
                 (COALESCE(f.human_answer,f.proposed_answer) IS NULL OR f.validation_status<>'draft_ready'))
                OR (COALESCE(f.human_answer,f.proposed_answer) IS NOT NULL AND f.requires_review AND f.review_status<>'reviewed'))) THEN
            RAISE EXCEPTION 'Approval requires current profile, resume, destination and reviewed answers';
        END IF;
    ELSIF NEW.lifecycle_state IN ('approved_for_manual_handoff','external_application_opened') THEN
        RAISE EXCEPTION 'Handoff requires revision approval';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.application_field_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE p public.application_packets;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application fields retain audit history'; END IF;
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown','withdrawn','abandoned') THEN RAISE EXCEPTION 'Closed application fields are immutable'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (NEW.id,NEW.packet_id,NEW.position,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.packet_id,OLD.position,OLD.created_at) THEN
            RAISE EXCEPTION 'Application field identity is immutable';
        END IF;
        IF p.lifecycle_state<>'preparing' THEN
            UPDATE public.application_packets SET revision=revision+1,approved_revision=NULL,lifecycle_state='needs_input',readiness_state='needs_review' WHERE id=NEW.packet_id;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['answer_revision','review_status','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['answer_revision','review_status','updated_at']) THEN
            NEW.answer_revision:=OLD.answer_revision+1; NEW.review_status:='pending';
        END IF;
        NEW.updated_at:=clock_timestamp();
    ELSIF p.approved_revision IS NOT NULL THEN RAISE EXCEPTION 'Invalidate approval before adding fields'; END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.application_history_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE p public.application_packets;
BEGIN
    SELECT * INTO p FROM public.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF TG_TABLE_NAME='application_submission_evidence' THEN
      IF NEW.confirmation_source='naukri_status_ui' THEN
        IF p.lifecycle_state NOT IN ('submitting','submission_unknown') OR NEW.packet_revision<>p.revision+1
           OR NOT EXISTS (
            SELECT 1 FROM public.owner_preferences r
            JOIN public.owner_preferences w ON w.key='apply_work:'||(r.value->>'queue_id')
            WHERE r.key=NEW.receipt_reference AND r.key='naukri_worker_receipt:'||(r.value->>'requisition')
              AND r.value->>'worker_dispatched'='true' AND r.value->>'persistent_after_reload'='true'
              AND r.value->>'status'='Application Sent'
              AND r.value->>'confirmation_source'='naukri_application_status_ui'
              AND r.value->>'operation_mode'='recurring_worker_ui'
              AND w.value->>'packet_id'=p.id::text AND w.value->>'job_id'=p.job_id::text
              AND w.value->>'candidate_profile_id'=p.candidate_profile_id::text
              AND w.value->>'account_sha256'=r.value->>'account_sha256'
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.value->'admitted_actions') a
                          WHERE a->>'fingerprint' LIKE 'apply:%')
        ) THEN RAISE EXCEPTION 'Worker evidence requires the original active submission claim'; END IF;
        RETURN NEW;
      END IF;
    END IF;
    IF NEW.packet_revision<>p.revision THEN RAISE EXCEPTION 'History must reference the current packet revision'; END IF;
    IF TG_TABLE_NAME='application_events' THEN
        IF NEW.next_state<>p.lifecycle_state THEN RAISE EXCEPTION 'Event state must match packet'; END IF;
        IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.application_submission_evidence e WHERE e.id=NEW.evidence_id AND e.packet_id=NEW.packet_id
        ) THEN RAISE EXCEPTION 'Evidence belongs to a different application'; END IF;
    ELSIF p.lifecycle_state<>'preparing' THEN RAISE EXCEPTION 'Submission evidence requires an explicit revision claim'; END IF;
    RETURN NEW;
END;
$function$;

COMMIT;
