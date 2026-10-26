-- LOCAL TEST PROPOSAL ONLY. Requires 001_mock_submission in a fresh disposable
-- localhost test database. This is not a production migration or R1/R2 approval.
-- Preserve the original V1 proposal and all unrelated guard/ACL logic verbatim.
BEGIN;
ALTER TABLE job_agent.browser_submission_attempts
 DROP CONSTRAINT browser_submission_attempts_adapter_check;
ALTER TABLE job_agent.browser_submission_attempts
 ADD CONSTRAINT browser_submission_attempts_adapter_check
 CHECK(adapter IN ('local_mock_v1','local_mock_v2'));

DO $patch$
DECLARE original text; revised text; anchor text;
BEGIN
 original:=pg_get_functiondef('job_agent.application_packet_guard()'::regprocedure);
 anchor:=$old$AND a.receipt->>'status'='accepted' AND a.receipt->>'fixture'='automated-apply-employer-v1'$old$;
 IF position(anchor IN original)=0 THEN RAISE EXCEPTION 'Unexpected mock packet guard'; END IF;
 revised:=replace(original,anchor,$new$AND a.receipt->>'status'='accepted'
       AND g.binding->>'adapter'=a.adapter
       AND a.receipt->>'fixture'=CASE a.adapter
           WHEN 'local_mock_v1' THEN 'automated-apply-employer-v1'
           WHEN 'local_mock_v2' THEN 'automated-apply-employer-v2' END$new$);
 EXECUTE revised;

 original:=pg_get_functiondef('job_agent.browser_execution_guard()'::regprocedure);
 anchor:=$old$OR g.binding->>'adapter' IS DISTINCT FROM 'local_mock_v1'$old$;
 IF position(anchor IN original)=0 THEN RAISE EXCEPTION 'Unexpected mock authorization guard'; END IF;
 revised:=replace(original,anchor,$new$OR NEW.adapter NOT IN ('local_mock_v1','local_mock_v2')
      OR g.binding->>'adapter' IS DISTINCT FROM NEW.adapter$new$);
 anchor:=$old$OR NEW.receipt->>'fixture' IS DISTINCT FROM 'automated-apply-employer-v1'$old$;
 IF position(anchor IN revised)=0 THEN RAISE EXCEPTION 'Unexpected mock receipt guard'; END IF;
 revised:=replace(revised,anchor,$new$OR NEW.receipt->>'fixture' IS DISTINCT FROM CASE NEW.adapter
          WHEN 'local_mock_v1' THEN 'automated-apply-employer-v1'
          WHEN 'local_mock_v2' THEN 'automated-apply-employer-v2' END$new$);
 EXECUTE revised;
END;
$patch$;
-- No grants, runtime roles, policies or production inventory entries are added.
COMMIT;
