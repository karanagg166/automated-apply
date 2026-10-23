-- LOCAL DEVELOPMENT PROPOSAL ONLY. Apply only to a fresh disposable PostgreSQL
-- fixture. Not production migration/ACL inventory or Phase 9 R1/R2 approval.
BEGIN;
ALTER TABLE job_agent.application_packet_fields
 DROP CONSTRAINT application_packet_fields_field_type_check;
ALTER TABLE job_agent.application_packet_fields
 ADD CONSTRAINT application_packet_fields_field_type_check
 CHECK(field_type IN ('text','textarea','url','file','multiple_choice','yes_no','multi_select'));

CREATE FUNCTION job_agent.valid_multi_select_answer(answer text, options jsonb, required boolean)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb; label text; seen text[] := '{}'; chosen jsonb;
BEGIN
 IF jsonb_typeof(options) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(options) NOT BETWEEN 1 AND 50 THEN RETURN false; END IF;
 FOR item IN SELECT jsonb_array_elements(options) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
  label:=item #>> '{}';
  IF length(btrim(label))=0 OR length(label)>200 OR lower(label)=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,lower(label));
 END LOOP;
 IF answer IS NULL THEN RETURN true; END IF;
 BEGIN chosen:=answer::jsonb; EXCEPTION WHEN data_exception THEN RETURN false; END;
 IF jsonb_typeof(chosen) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(chosen)>50 OR (required AND jsonb_array_length(chosen)=0) THEN RETURN false; END IF;
 seen:='{}';
 FOR item IN SELECT jsonb_array_elements(chosen) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
  label:=item #>> '{}';
  IF label=ANY(seen) OR NOT (options ? label) THEN RETURN false; END IF;
  seen:=array_append(seen,label);
 END LOOP;
 RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION job_agent.valid_multi_select_answer(text,jsonb,boolean) FROM PUBLIC;
ALTER TABLE job_agent.application_packet_fields
 ADD CONSTRAINT ck_application_fields_multi_select_v1 CHECK (
  field_type<>'multi_select' OR (
   job_agent.valid_multi_select_answer(proposed_answer,options,required)
   AND job_agent.valid_multi_select_answer(human_answer,options,required)
  )
 );
-- No runtime grants, guard replacements, policies or production inventory changes.
COMMIT;
