WITH verified AS (
    SELECT jsonb_build_object('id',p.id,'version',p.version,'verified_skills',p.verified_skills,
        'verified_experience_years',p.verified_experience_years,'preferences',p.preferences) AS profile
    FROM candidate_profiles p JOIN owner_preferences c ON c.key='phase1_profile_confirmation'
    WHERE p.singleton_key='primary' AND c.value->>'profile_id'=p.id::text
        AND c.value->'profile_version'=to_jsonb(p.version)
        AND jsonb_typeof(c.value->'confirmed_at')='string' AND NULLIF(c.value->>'confirmed_at','') IS NOT NULL LIMIT 1
), saved AS (
    SELECT j.id,j.company_id,j.source_platform,j.created_at,j.status,j.title,j.discovery_metadata,
        NULLIF(regexp_replace(j.job_url,'[?#].*$','',''),'') AS job_link,
        NULLIF(regexp_replace(j.application_url,'[?#].*$','',''),'') AS application_link,
        CASE WHEN j.source_platform='naukri' THEN
            substring(regexp_replace(j.job_url,'[?#].*$','','') from '-([0-9]{10,20})/?$')
        END AS requisition
    FROM jobs j CROSS JOIN verified
    WHERE ($1::text IS NULL OR j.source_platform=$1) AND j.status<>'archived'
), submitted AS MATERIALIZED (
    SELECT j.id,j.source_platform,
        NULLIF(regexp_replace(j.job_url,'[?#].*$','',''),'') AS job_link,
        NULLIF(regexp_replace(j.application_url,'[?#].*$','',''),'') AS application_link,
        CASE WHEN j.source_platform='naukri' THEN
            substring(regexp_replace(j.job_url,'[?#].*$','','') from '-([0-9]{10,20})/?$')
        END AS requisition
    FROM jobs j WHERE j.status IN ('applied','submitted') OR EXISTS (
        SELECT 1 FROM application_packets a WHERE a.job_id=j.id AND a.lifecycle_state IN (
            'user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown'
        )
    )
), mailbox_history AS MATERIALIZED (
    SELECT p.value FROM owner_preferences p
    WHERE starts_with(p.key,'gmail_application:')
        AND p.value->'confirmed_application'='true'::jsonb
        AND COALESCE(p.value->'deleted','false'::jsonb)<>'true'::jsonb
        AND CASE WHEN p.value->>'expires_at' ~* '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$'
                 AND pg_input_is_valid(p.value->>'expires_at','timestamp with time zone')
            THEN (p.value->>'expires_at')::timestamptz > statement_timestamp()
            ELSE true END
), classified AS MATERIALIZED (
    SELECT j.id,j.source_platform,j.created_at,(
        COALESCE(j.discovery_metadata->'data_provenance'->>'posting_status'='already_applied',false) OR
        EXISTS (SELECT 1 FROM submitted prior WHERE prior.id=j.id
            OR prior.job_link IN (j.job_link,j.application_link)
            OR prior.application_link IN (j.job_link,j.application_link)
            OR (prior.source_platform=j.source_platform AND prior.requisition=j.requisition)) OR
        EXISTS (SELECT 1 FROM owner_preferences p WHERE j.requisition IS NOT NULL AND p.key IN (
            'naukri_receipt:'||j.requisition,'naukri_worker_receipt:'||j.requisition
        )) OR
        EXISTS (SELECT 1 FROM owner_preferences p WHERE starts_with(p.key,'apply_work:')
            AND (p.value->>'job_id'=j.id::text OR (j.requisition IS NOT NULL AND p.value->>'requisition'=j.requisition))
            AND (p.value->>'stage' IN ('APPLYING','QUESTIONS','RESUME_ATTACHMENT','VERIFYING','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED','SUBMITTED_RECORDED')
                OR p.value->>'status'='unknown'
                OR COALESCE(p.value->'form_loss_observation','null'::jsonb)<>'null'::jsonb
                OR COALESCE(p.value->'admitted_actions','[]'::jsonb)<>'[]'::jsonb)) OR
        EXISTS (SELECT 1 FROM mailbox_history p WHERE
            regexp_replace(p.value->>'job_url','[?#].*$','','') IN (j.job_link,j.application_link)
            OR (NULLIF(p.value->>'job_url','') IS NULL AND lower(trim(p.value->>'company'))=lower(trim(c.name))
                AND lower(trim(p.value->>'role'))=lower(trim(j.title)))
        )
    ) AS blocked
    FROM saved j LEFT JOIN companies c ON c.id=j.company_id
), eligible AS (
    SELECT id,created_at,row_number() OVER (PARTITION BY source_platform ORDER BY created_at DESC,id) AS source_position
    FROM classified WHERE NOT blocked
    ORDER BY source_position,created_at DESC,id LIMIT 100
), projected AS (
SELECT jsonb_build_object(
    'id',j.id,'company_id',j.company_id,'source_platform',j.source_platform,
    'source_verification_status',j.source_verification_status,
    'listing',jsonb_build_object(
        'title',j.title,'description',j.description,'skills_required',j.skills_required,
        'location',j.location,'is_remote',j.is_remote,'remote_type',COALESCE(j.remote_type,'unknown'),
        'experience_level',j.experience_level,'employment_type',j.employment_type,
        'salary_min',j.salary_min,'salary_max',j.salary_max,'salary_currency',j.salary_currency,
        'salary_period',j.salary_period,'date_posted',j.date_posted
    ),
    'company',CASE WHEN c.id IS NULL THEN NULL ELSE jsonb_build_object(
        'name',c.name,'domain',c.domain,'startup_stage',c.metadata->'startup_discovery'->>'stage',
        'startup_source',c.metadata->'startup_discovery'->>'source'
    ) END
) AS value
FROM eligible e JOIN jobs j ON j.id=e.id LEFT JOIN companies c ON c.id=j.company_id
)
SELECT jsonb_build_object(
    'profile',(SELECT profile FROM verified),
    'excluded_prior_or_unknown',(SELECT count(*) FROM classified WHERE blocked),
    'jobs',COALESCE((SELECT jsonb_agg(value) FROM projected),'[]'::jsonb)
)
