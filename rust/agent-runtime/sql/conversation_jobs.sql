WITH candidates AS (
    SELECT j.*, substring(regexp_replace(j.job_url, '[?#].*$', '') from '-([0-9]{10,20})/?$') AS requisition
    FROM jobs j
    WHERE ($1::uuid[] IS NULL OR j.id = ANY($1))
        AND ($2::text IS NULL OR EXISTS (
            SELECT 1 FROM companies c WHERE c.id = j.company_id AND lower(c.name) = $2
        ))
        AND (NOT $3::boolean OR NOT EXISTS (
            SELECT 1 FROM application_packets p JOIN application_submission_evidence e ON e.packet_id = p.id
            WHERE p.job_id = j.id
        ))
    ORDER BY j.created_at DESC, j.id
    LIMIT 201
)
SELECT
    CASE WHEN octet_length(coalesce(j.description, '')) <= 65536
              AND octet_length(j.job_url) <= 2048
              AND octet_length(coalesce(j.application_url, '')) <= 2048
              AND octet_length(coalesce(to_jsonb(j.skills_required)::text, '')) <= 8192
    THEN jsonb_build_object(
        'id', j.id, 'title', j.title, 'status', j.status, 'job_url', j.job_url,
        'application_url', j.application_url, 'date_posted', j.date_posted,
        'location', j.location, 'remote_type', j.remote_type, 'employment_type', j.employment_type,
        'source_platform', j.source_platform, 'skills_required', j.skills_required,
        'description', j.description, 'match_score', j.match_score, 'salary_min', j.salary_min,
        'salary_max', j.salary_max, 'salary_currency', j.salary_currency, 'salary_period', j.salary_period
    ) END AS job,
    CASE WHEN c.id IS NOT NULL THEN jsonb_build_object(
        'name', c.name, 'metadata_', jsonb_build_object('startup_discovery', jsonb_build_object(
            'stage', c.metadata->'startup_discovery'->'stage',
            'employee_count', c.metadata->'startup_discovery'->'employee_count'
        ))
    ) END AS company,
    (
        j.status IN ('applied', 'submitted')
        OR j.discovery_metadata->'data_provenance'->>'posting_status' = 'already_applied'
        OR EXISTS (
            SELECT 1 FROM application_packets p
            WHERE p.job_id = j.id AND (
                p.lifecycle_state IN ('user_reported_submitted', 'provider_confirmed_submitted', 'submitting', 'submission_unknown')
                OR EXISTS (SELECT 1 FROM application_submission_evidence e WHERE e.packet_id = p.id)
            )
        )
        OR (
            j.source_platform = 'naukri' AND j.requisition IS NOT NULL AND (
                EXISTS (
                    SELECT 1 FROM owner_preferences p
                    WHERE p.key IN ('naukri_receipt:' || j.requisition, 'naukri_worker_receipt:' || j.requisition)
                )
                OR EXISTS (
                    SELECT 1 FROM jobs prior JOIN application_packets p ON p.job_id = prior.id
                    WHERE prior.source_platform = 'naukri'
                        AND substring(regexp_replace(prior.job_url, '[?#].*$', '') from '-([0-9]{10,20})/?$') = j.requisition
                        AND p.lifecycle_state IN ('user_reported_submitted', 'provider_confirmed_submitted', 'submitting', 'submission_unknown')
                )
            )
        )
        OR EXISTS (
            SELECT 1 FROM owner_preferences p
            WHERE starts_with(p.key, 'apply_work:')
                AND (p.value->>'job_id' = j.id::text OR (
                    j.source_platform = 'naukri' AND p.value->>'requisition' = j.requisition
                ))
                AND (
                    p.value->>'stage' IN ('APPLYING', 'QUESTIONS', 'RESUME_ATTACHMENT', 'VERIFYING', 'SUBMISSION_UNKNOWN', 'SUBMITTED_CONFIRMED', 'SUBMITTED_RECORDED')
                    OR coalesce(p.value->'admitted_actions', '[]'::jsonb) <> '[]'::jsonb
                )
        )
    ) IS TRUE AS has_application_history
FROM candidates j LEFT JOIN companies c ON c.id = j.company_id
ORDER BY j.created_at DESC, j.id
