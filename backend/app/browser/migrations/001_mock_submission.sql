-- PROPOSED browser execution extension. Not part of the approved Phase 9 baseline.
-- Apply ONLY to a newly created disposable localhost test database for now.
-- Production installation/ACL/catalog acceptance requires separate review and approval.
BEGIN;
CREATE TABLE job_agent.browser_submission_grants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 packet_id uuid NOT NULL REFERENCES job_agent.application_packets(id),
 packet_revision integer NOT NULL CHECK(packet_revision>=1),
 preview_digest varchar(64) NOT NULL CHECK(preview_digest ~ '^[a-f0-9]{64}$'),
 token_hash varchar(64) NOT NULL UNIQUE CHECK(token_hash ~ '^[a-f0-9]{64}$'),
 binding jsonb NOT NULL CHECK(jsonb_typeof(binding)='object' AND octet_length(binding::text)<=65536),
 expires_at timestamptz NOT NULL, consumed_at timestamptz, revoked_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '5 minutes'),
 CHECK(consumed_at IS NULL OR revoked_at IS NULL),
 CHECK(consumed_at IS NULL OR (consumed_at>=created_at AND consumed_at<=expires_at))
);
CREATE INDEX browser_grant_packet ON job_agent.browser_submission_grants(packet_id);
CREATE TABLE job_agent.browser_submission_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 packet_id uuid NOT NULL UNIQUE REFERENCES job_agent.application_packets(id),
 grant_id uuid NOT NULL UNIQUE REFERENCES job_agent.browser_submission_grants(id),
 packet_revision integer NOT NULL CHECK(packet_revision>=1),
 idempotency_key varchar(100) NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{8,100}$'),
 request_hash varchar(64) NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
 adapter varchar(40) NOT NULL CHECK(adapter='local_mock_v1'),
 destination varchar(2048) NOT NULL,
 payload_digest varchar(64) NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 state varchar(20) NOT NULL CHECK(state IN ('dispatched','unknown','verified')),
 dispatched_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz NOT NULL,
 finished_at timestamptz, receipt jsonb, diagnostic text,
 evidence_id uuid UNIQUE REFERENCES job_agent.application_submission_evidence(id),
 CHECK(lease_until>dispatched_at AND lease_until<=dispatched_at+interval '60 seconds'),
 CHECK(receipt IS NULL OR (jsonb_typeof(receipt)='object' AND octet_length(receipt::text)<=8192)),
 CHECK((state='verified')=(receipt IS NOT NULL)),
 CHECK(evidence_id IS NULL OR state='verified')
);
ALTER TABLE job_agent.application_packets DROP CONSTRAINT application_packets_lifecycle_state_check;
ALTER TABLE job_agent.application_packets ADD CONSTRAINT application_packets_lifecycle_state_check CHECK(lifecycle_state IN
 ('created','preparing','needs_input','ready_for_review','reviewed','approved_for_manual_handoff','external_application_opened',
  'user_reported_submitted','provider_confirmed_submitted','withdrawn','abandoned','submitting','submission_unknown'));
ALTER TABLE job_agent.application_packets DROP CONSTRAINT application_packets_tracking_state_check;
ALTER TABLE job_agent.application_packets ADD CONSTRAINT application_packets_tracking_state_check CHECK(tracking_state IN
 ('not_applied','applied_manually','applied_verified','application_incomplete','application_rejected','interview_scheduled','offer_received','archived'));
ALTER TABLE job_agent.application_packets DROP CONSTRAINT application_packets_readiness_state_check;
ALTER TABLE job_agent.application_packets ADD CONSTRAINT application_packets_readiness_state_check CHECK(readiness_state IN
 ('needs_profile','needs_input','needs_resume','needs_review','ready_for_manual_handoff','manual_action_required','completed_by_user','completed_verified','unsupported'));
ALTER TABLE job_agent.application_submission_evidence DROP CONSTRAINT application_submission_evidence_confirmation_source_check;
ALTER TABLE job_agent.application_submission_evidence DROP CONSTRAINT application_submission_evidence_evidence_confidence_check;
ALTER TABLE job_agent.application_submission_evidence DROP CONSTRAINT application_submission_evidence_human_confirmed_check;
ALTER TABLE job_agent.application_submission_evidence ADD CONSTRAINT browser_evidence_kind CHECK(
 (confirmation_source='user_reported' AND evidence_confidence='self_reported_unverified' AND human_confirmed)
 OR (confirmation_source='mock_employer' AND evidence_confidence='mock_receipt_verified' AND NOT human_confirmed));

-- Preserve the historical guard's remaining logic. Fail if its reviewed anchor changed.
DO $patch$
DECLARE old_definition text; revised text; anchor text;
BEGIN
 old_definition:=pg_get_functiondef('job_agent.application_packet_guard()'::regprocedure);
 anchor:=$anchor$    IF NEW.lifecycle_state='provider_confirmed_submitted' THEN
        RAISE EXCEPTION 'No authorized submission provider exists in Phase 5A';
    END IF;$anchor$;
 IF position(anchor IN old_definition)=0 THEN RAISE EXCEPTION 'Unexpected baseline application guard'; END IF;
 revised:=replace(old_definition,anchor,$new$
    IF NEW.lifecycle_state='provider_confirmed_submitted' AND NOT EXISTS (
       SELECT 1 FROM job_agent.application_submission_evidence e
       JOIN job_agent.browser_submission_attempts a ON a.evidence_id=e.id AND a.packet_id=e.packet_id
       JOIN job_agent.browser_submission_grants g ON g.id=a.grant_id AND g.packet_id=a.packet_id
       WHERE e.packet_id=NEW.id AND e.confirmation_source='mock_employer' AND a.state='verified'
       AND g.consumed_at IS NOT NULL AND g.revoked_at IS NULL
       AND a.receipt->>'status'='accepted' AND a.receipt->>'fixture'='automated-apply-employer-v1'
       AND a.receipt->>'attempt_id'=a.id::text AND a.receipt->>'payload_digest'=a.payload_digest
    ) THEN RAISE EXCEPTION 'Provider confirmation requires a verified authorized mock receipt'; END IF;
    IF NEW.lifecycle_state IN ('submitting','submission_unknown') AND NOT EXISTS (
       SELECT 1 FROM job_agent.browser_submission_attempts a WHERE a.packet_id=NEW.id
       AND a.state IN ('dispatched','unknown')
    ) THEN RAISE EXCEPTION 'Execution state requires a durable dispatch record'; END IF;
    IF TG_OP='UPDATE' AND OLD.lifecycle_state='provider_confirmed_submitted'
       AND NEW.lifecycle_state NOT IN ('provider_confirmed_submitted','withdrawn') THEN
       RAISE EXCEPTION 'Verified submission history cannot be erased'; END IF;
    IF NEW.tracking_state='applied_verified' AND NOT EXISTS (
       SELECT 1 FROM job_agent.application_submission_evidence e WHERE e.packet_id=NEW.id AND e.confirmation_source='mock_employer'
    ) THEN RAISE EXCEPTION 'Verified tracking requires verified evidence'; END IF;
    IF NEW.tracking_state='applied_verified' AND NEW.lifecycle_state NOT IN ('provider_confirmed_submitted','withdrawn') THEN
       RAISE EXCEPTION 'Verified tracking requires verified submission'; END IF;
$new$);
 revised:=replace(revised,'''user_reported_submitted'',''withdrawn'',''abandoned''',
                         '''user_reported_submitted'',''provider_confirmed_submitted'',''submitting'',''submission_unknown'',''withdrawn'',''abandoned''');
 EXECUTE revised;
 old_definition:=pg_get_functiondef('job_agent.application_field_guard()'::regprocedure);
 revised:=replace(old_definition,'''user_reported_submitted'',''withdrawn'',''abandoned''',
   '''user_reported_submitted'',''provider_confirmed_submitted'',''submitting'',''submission_unknown'',''withdrawn'',''abandoned''');
 IF revised=old_definition THEN RAISE EXCEPTION 'Unexpected baseline field guard'; END IF;
 EXECUTE revised;
END;
$patch$;

CREATE FUNCTION job_agent.browser_execution_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE g job_agent.browser_submission_grants; p job_agent.application_packets;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Browser execution history cannot be deleted'; END IF;
 IF TG_TABLE_NAME='browser_submission_grants' THEN
   IF TG_OP='UPDATE' THEN
     IF (to_jsonb(NEW)-ARRAY['consumed_at','revoked_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['consumed_at','revoked_at'])
        OR OLD.consumed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'Grant is immutable or already consumed'; END IF;
   END IF;
 ELSE
   SELECT * INTO g FROM job_agent.browser_submission_grants WHERE id=NEW.grant_id;
   SELECT * INTO p FROM job_agent.application_packets WHERE id=NEW.packet_id;
   IF g.packet_id<>NEW.packet_id OR g.consumed_at IS NULL OR g.revoked_at IS NOT NULL
      OR g.preview_digest IS DISTINCT FROM g.binding->>'preview_digest'
      OR g.binding->>'adapter' IS DISTINCT FROM 'local_mock_v1'
      OR NEW.payload_digest IS DISTINCT FROM g.binding->>'payload_digest'
      OR NEW.destination IS DISTINCT FROM g.binding->>'destination'
      OR g.packet_revision+1<>NEW.packet_revision THEN RAISE EXCEPTION 'Attempt lacks exact consumed authorization'; END IF;
   IF TG_OP='INSERT' AND (g.expires_at<clock_timestamp() OR p.revision<>NEW.packet_revision OR p.lifecycle_state<>'preparing'
      OR NEW.state<>'dispatched' OR NEW.receipt IS NOT NULL OR NEW.evidence_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Invalid browser dispatch reservation'; END IF;
   IF TG_OP='UPDATE' THEN
     IF (to_jsonb(NEW)-ARRAY['state','finished_at','receipt','evidence_id','diagnostic']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['state','finished_at','receipt','evidence_id','diagnostic'])
        OR OLD.state='verified' OR (OLD.state='unknown' AND NEW.state NOT IN ('unknown','verified')) THEN
        RAISE EXCEPTION 'Browser attempts never replay or erase verified outcomes'; END IF;
   END IF;
   IF NEW.state='verified' AND (NEW.receipt->>'status' IS DISTINCT FROM 'accepted'
      OR NEW.receipt->>'fixture' IS DISTINCT FROM 'automated-apply-employer-v1'
      OR NEW.receipt->>'attempt_id' IS DISTINCT FROM NEW.id::text
      OR NEW.receipt->>'payload_digest' IS DISTINCT FROM NEW.payload_digest) THEN
      RAISE EXCEPTION 'Receipt does not match dispatched application'; END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER browser_grant_guard BEFORE UPDATE OR DELETE ON job_agent.browser_submission_grants
 FOR EACH ROW EXECUTE FUNCTION job_agent.browser_execution_guard();
CREATE TRIGGER browser_attempt_guard BEFORE INSERT OR UPDATE OR DELETE ON job_agent.browser_submission_attempts
 FOR EACH ROW EXECUTE FUNCTION job_agent.browser_execution_guard();

-- Deferred consistency permits the short preparing claim inside a transaction, but
-- never a committed packet that erases an active or verified external outcome.
CREATE FUNCTION job_agent.browser_outcome_consistency() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a job_agent.browser_submission_attempts; p job_agent.application_packets; target uuid;
BEGIN
 IF TG_TABLE_NAME='application_packets' THEN target:=NEW.id; ELSE target:=NEW.packet_id; END IF;
 SELECT * INTO a FROM job_agent.browser_submission_attempts WHERE packet_id=target;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO p FROM job_agent.application_packets WHERE id=target;
 IF (a.state='dispatched' AND p.lifecycle_state<>'submitting')
    OR (a.state='unknown' AND p.lifecycle_state<>'submission_unknown')
    OR (a.state='verified' AND (p.lifecycle_state NOT IN ('provider_confirmed_submitted','withdrawn') OR a.evidence_id IS NULL)) THEN
    RAISE EXCEPTION 'Packet and durable browser outcome must remain consistent'; END IF;
 RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER browser_packet_outcome AFTER UPDATE ON job_agent.application_packets
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION job_agent.browser_outcome_consistency();
CREATE CONSTRAINT TRIGGER browser_attempt_outcome AFTER INSERT OR UPDATE ON job_agent.browser_submission_attempts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION job_agent.browser_outcome_consistency();
REVOKE ALL ON FUNCTION job_agent.browser_outcome_consistency() FROM PUBLIC;

-- No client/backend grants or production runtime policies are installed by this proposal.
ALTER TABLE job_agent.browser_submission_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_agent.browser_submission_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON job_agent.browser_submission_grants,job_agent.browser_submission_attempts FROM PUBLIC;
REVOKE ALL ON FUNCTION job_agent.browser_execution_guard() FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
     EXECUTE format('REVOKE ALL ON job_agent.browser_submission_grants,job_agent.browser_submission_attempts FROM %I',role_name);
   END IF;
 END LOOP;
END; $$;
COMMIT;
