-- Phase 5A: additive, backend-only manual application preparation. No production execution hook.
BEGIN;

-- Composite ownership prevents a packet from selecting another candidate's resource.
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_resource_owner ON job_agent.candidate_resources(id,candidate_profile_id);
CREATE TABLE IF NOT EXISTS job_agent.application_packets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES job_agent.jobs(id),
    candidate_profile_id UUID NOT NULL REFERENCES job_agent.candidate_profiles(id),
    candidate_profile_version INTEGER NOT NULL CHECK(candidate_profile_version>=1),
    resume_resource_id UUID,
    FOREIGN KEY(resume_resource_id,candidate_profile_id) REFERENCES job_agent.candidate_resources(id,candidate_profile_id),
    application_url VARCHAR(2048),
    platform VARCHAR(50) NOT NULL,
    lifecycle_state VARCHAR(40) NOT NULL DEFAULT 'created' CHECK(lifecycle_state IN
        ('created','preparing','needs_input','ready_for_review','reviewed','approved_for_manual_handoff',
         'external_application_opened','user_reported_submitted','provider_confirmed_submitted','withdrawn','abandoned')),
    tracking_state VARCHAR(40) NOT NULL DEFAULT 'not_applied' CHECK(tracking_state IN
        ('not_applied','applied_manually','application_incomplete','application_rejected','interview_scheduled','offer_received','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
    approved_revision INTEGER CHECK(approved_revision IS NULL OR approved_revision=revision),
    readiness_state VARCHAR(40) NOT NULL CHECK(readiness_state IN
        ('needs_profile','needs_input','needs_resume','needs_review','ready_for_manual_handoff','manual_action_required','completed_by_user','unsupported')),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=262144),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_application_packet_candidate_job UNIQUE(job_id,candidate_profile_id)
);
CREATE INDEX IF NOT EXISTS ix_application_packet_platform_state ON job_agent.application_packets(platform,lifecycle_state,created_at);

CREATE TABLE IF NOT EXISTS job_agent.application_packet_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL REFERENCES job_agent.application_packets(id),
    position INTEGER NOT NULL CHECK(position BETWEEN 0 AND 99),
    question TEXT NOT NULL CHECK(length(trim(question)) BETWEEN 1 AND 2000),
    category VARCHAR(40) NOT NULL CHECK(category IN
        ('personal_information','contact_information','professional_profile_url','education','experience','technical_skills',
         'resume_upload','salary','notice_period','work_authorization','project_explanation','motivation','free_text','multiple_choice','yes_no','unknown')),
    field_type VARCHAR(30) NOT NULL CHECK(field_type IN ('text','textarea','url','file','multiple_choice','yes_no')),
    required BOOLEAN NOT NULL,
    max_characters INTEGER NOT NULL CHECK(max_characters BETWEEN 1 AND 10000),
    max_words INTEGER CHECK(max_words BETWEEN 1 AND 1500),
    constraints VARCHAR(1000),
    options JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(options)='array' AND jsonb_array_length(options)<=50),
    writing_style VARCHAR(30) NOT NULL CHECK(writing_style IN ('professional','conversational','technical','concise','founder_focused')),
    proposed_answer TEXT CHECK(proposed_answer IS NULL OR length(trim(proposed_answer)) BETWEEN 1 AND 10000),
    human_answer TEXT CHECK(human_answer IS NULL OR length(trim(human_answer)) BETWEEN 1 AND 10000),
    provenance JSONB NOT NULL CHECK(jsonb_typeof(provenance)='object' AND octet_length(provenance::text)<=16384),
    validation_status VARCHAR(30) NOT NULL CHECK(validation_status IN ('draft_ready','needs_input','file_upload_required','provider_unavailable','validation_failed')),
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','reviewed')),
    requires_review BOOLEAN NOT NULL DEFAULT true,
    missing_information JSONB NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(missing_information)='array'),
    answer_revision INTEGER NOT NULL DEFAULT 1 CHECK(answer_revision>=1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_packet_field_position UNIQUE(packet_id,position),
    CHECK(field_type NOT IN ('multiple_choice','yes_no') OR jsonb_array_length(options)>0),
    CHECK(COALESCE(human_answer,proposed_answer) IS NULL OR length(COALESCE(human_answer,proposed_answer))<=max_characters)
);
CREATE INDEX IF NOT EXISTS ix_application_packet_fields_packet_id ON job_agent.application_packet_fields(packet_id);

CREATE TABLE IF NOT EXISTS job_agent.application_submission_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL UNIQUE REFERENCES job_agent.application_packets(id),
    packet_revision INTEGER NOT NULL CHECK(packet_revision>=1),
    -- There is no authorized submission provider in Phase 5A. Extend in a future migration only.
    confirmation_source VARCHAR(30) NOT NULL DEFAULT 'user_reported' CHECK(confirmation_source='user_reported'),
    receipt_reference VARCHAR(255),
    evidence_confidence VARCHAR(40) NOT NULL DEFAULT 'self_reported_unverified' CHECK(evidence_confidence='self_reported_unverified'),
    human_confirmed BOOLEAN NOT NULL CHECK(human_confirmed),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
    request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_agent.application_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    packet_id UUID NOT NULL REFERENCES job_agent.application_packets(id),
    event_type VARCHAR(50) NOT NULL CHECK(event_type IN
        ('packet_created','packet_refreshed','questions_added','answer_generated','answer_edited','packet_reviewed','packet_approved','tracking_updated','user_reported_submission')),
    previous_state VARCHAR(40), next_state VARCHAR(40) NOT NULL,
    packet_revision INTEGER NOT NULL CHECK(packet_revision>=1),
    origin VARCHAR(20) NOT NULL CHECK(origin IN ('owner_rest','system')),
    evidence_id UUID REFERENCES job_agent.application_submission_evidence(id),
    note VARCHAR(1000), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_events_packet_revision ON job_agent.application_events(packet_id,packet_revision);

CREATE OR REPLACE FUNCTION job_agent.application_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Application history is append only'; END;
$$;
CREATE OR REPLACE TRIGGER application_events_immutable BEFORE UPDATE OR DELETE ON job_agent.application_events
FOR EACH ROW EXECUTE FUNCTION job_agent.application_append_only();
CREATE OR REPLACE TRIGGER application_submission_immutable BEFORE UPDATE OR DELETE ON job_agent.application_submission_evidence
FOR EACH ROW EXECUTE FUNCTION job_agent.application_append_only();

CREATE OR REPLACE FUNCTION job_agent.application_packet_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
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
        SELECT 1 FROM job_agent.application_submission_evidence e WHERE e.packet_id=NEW.id AND e.human_confirmed
    ) THEN RAISE EXCEPTION 'Manual submission requires explicit self-reported evidence'; END IF;
    IF NEW.tracking_state IN ('applied_manually','application_rejected','interview_scheduled','offer_received') AND NOT EXISTS (
        SELECT 1 FROM job_agent.application_submission_evidence e WHERE e.packet_id=NEW.id
    ) THEN RAISE EXCEPTION 'Post-submission tracking requires evidence'; END IF;
    IF NEW.approved_revision IS NOT NULL THEN
        IF NEW.lifecycle_state NOT IN ('approved_for_manual_handoff','external_application_opened') OR NEW.approved_revision<>NEW.revision
           OR NEW.candidate_profile_version<>(SELECT version FROM job_agent.candidate_profiles WHERE id=NEW.candidate_profile_id)
           OR NEW.application_url IS NULL OR NEW.resume_resource_id IS NULL
           OR NEW.snapshot->'destination'->>'valid' IS DISTINCT FROM 'true'
           OR NEW.snapshot->'destination'->>'source_confidence' IS DISTINCT FROM 'source_consistent'
           OR NEW.application_url IS DISTINCT FROM NEW.snapshot->'destination'->>'application_url'
           OR NEW.resume_resource_id::text IS DISTINCT FROM NEW.snapshot->'resume'->'selected'->>'resource_id'
           OR NOT EXISTS (SELECT 1 FROM job_agent.candidate_resources r WHERE r.id=NEW.resume_resource_id
                          AND r.candidate_profile_id=NEW.candidate_profile_id AND r.user_confirmed AND r.resource_type='resume'
                          AND r.url=NEW.snapshot->'resume'->'selected'->>'url')
           OR EXISTS (SELECT 1 FROM job_agent.application_packet_fields f WHERE f.packet_id=NEW.id AND
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
$$;
CREATE OR REPLACE TRIGGER application_packet_guard BEFORE INSERT OR UPDATE OR DELETE ON job_agent.application_packets
FOR EACH ROW EXECUTE FUNCTION job_agent.application_packet_guard();

CREATE OR REPLACE FUNCTION job_agent.application_field_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p job_agent.application_packets;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Application fields retain audit history'; END IF;
    SELECT * INTO p FROM job_agent.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF p.lifecycle_state IN ('user_reported_submitted','withdrawn','abandoned') THEN RAISE EXCEPTION 'Closed application fields are immutable'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (NEW.id,NEW.packet_id,NEW.position,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.packet_id,OLD.position,OLD.created_at) THEN
            RAISE EXCEPTION 'Application field identity is immutable';
        END IF;
        IF p.lifecycle_state<>'preparing' THEN
            UPDATE job_agent.application_packets SET revision=revision+1,approved_revision=NULL,lifecycle_state='needs_input',readiness_state='needs_review' WHERE id=NEW.packet_id;
        END IF;
        IF (to_jsonb(NEW)-ARRAY['answer_revision','review_status','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['answer_revision','review_status','updated_at']) THEN
            NEW.answer_revision:=OLD.answer_revision+1; NEW.review_status:='pending';
        END IF;
        NEW.updated_at:=clock_timestamp();
    ELSIF p.approved_revision IS NOT NULL THEN RAISE EXCEPTION 'Invalidate approval before adding fields'; END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER application_field_guard BEFORE INSERT OR UPDATE OR DELETE ON job_agent.application_packet_fields
FOR EACH ROW EXECUTE FUNCTION job_agent.application_field_guard();

CREATE OR REPLACE FUNCTION job_agent.application_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p job_agent.application_packets;
BEGIN
    SELECT * INTO p FROM job_agent.application_packets WHERE id=NEW.packet_id FOR UPDATE;
    IF NEW.packet_revision<>p.revision THEN RAISE EXCEPTION 'History must reference the current packet revision'; END IF;
    IF TG_TABLE_NAME='application_events' THEN
        IF NEW.next_state<>p.lifecycle_state THEN RAISE EXCEPTION 'Event state must match packet'; END IF;
        IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM job_agent.application_submission_evidence e WHERE e.id=NEW.evidence_id AND e.packet_id=NEW.packet_id
        ) THEN RAISE EXCEPTION 'Evidence belongs to a different application'; END IF;
    ELSIF p.lifecycle_state<>'preparing' THEN RAISE EXCEPTION 'Submission evidence requires an explicit revision claim'; END IF;
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER application_event_guard BEFORE INSERT ON job_agent.application_events
FOR EACH ROW EXECUTE FUNCTION job_agent.application_history_guard();
CREATE OR REPLACE TRIGGER application_evidence_guard BEFORE INSERT ON job_agent.application_submission_evidence
FOR EACH ROW EXECUTE FUNCTION job_agent.application_history_guard();

DO $$
DECLARE table_name text; client_role text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['application_packets','application_packet_fields','application_events','application_submission_evidence'] LOOP
        EXECUTE format('ALTER TABLE job_agent.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON job_agent.%I FROM PUBLIC',table_name);
        FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                EXECUTE format('REVOKE ALL ON job_agent.%I FROM %I',table_name,client_role);
            END IF;
        END LOOP;
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT SELECT,INSERT ON job_agent.%I TO service_role',table_name);
            IF table_name IN ('application_packets','application_packet_fields') THEN
                EXECUTE format('GRANT UPDATE ON job_agent.%I TO service_role',table_name);
            END IF;
        END IF;
    END LOOP;
END;
$$;
COMMIT;
