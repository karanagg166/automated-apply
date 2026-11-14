-- Reviewed backend-only ACL overlay. No schema/database/role authority is added.
DO $access$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'rust_agent_runs','rust_agent_events','rust_agent_control',
        'rust_agent_control_events','rust_telegram_runtime','rust_telegram_outbox'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO job_agent_owner',table_name);
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role,job_agent_runtime',table_name);
        EXECUTE format('CREATE POLICY job_agent_backend ON public.%I FOR ALL TO job_agent_runtime USING (true) WITH CHECK (true)',table_name);
        IF table_name IN ('rust_agent_events','rust_agent_control_events') THEN
            EXECUTE format('GRANT SELECT,INSERT ON public.%I TO job_agent_runtime',table_name);
        ELSE
            EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO job_agent_runtime',table_name);
        END IF;
    END LOOP;
END $access$;
