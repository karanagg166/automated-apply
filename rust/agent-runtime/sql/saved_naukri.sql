WITH verified AS (
    SELECT jsonb_build_object('id',p.id,'version',p.version,'verified_skills',p.verified_skills,
        'verified_experience_years',p.verified_experience_years,'preferences',p.preferences) AS profile
    FROM candidate_profiles p JOIN owner_preferences c ON c.key='phase1_profile_confirmation'
    WHERE p.singleton_key='primary' AND c.value->>'profile_id'=p.id::text
        AND c.value->'profile_version'=to_jsonb(p.version)
        AND NULLIF(c.value->>'confirmed_at','') IS NOT NULL LIMIT 1
), saved AS (
    SELECT j.*, substring(regexp_replace(j.job_url,'[?#].*$','','') from '-([0-9]{10,20})/?$') AS requisition
    FROM jobs j WHERE source_platform='naukri' AND status<>'archived'
    ORDER BY created_at DESC,id LIMIT 100
) , projected AS (
SELECT jsonb_build_object(
    'id',j.id,'company_id',j.company_id,'source_verification_status',j.source_verification_status,
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
    ) END,
    'blocked',(
        j.status IN ('applied','submitted') OR
        COALESCE(j.discovery_metadata->'data_provenance'->>'posting_status'='already_applied',false) OR
        EXISTS (SELECT 1 FROM application_packets a WHERE a.job_id=j.id AND a.lifecycle_state IN (
            'user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown'
        )) OR
        EXISTS (SELECT 1 FROM owner_preferences p WHERE j.requisition IS NOT NULL AND p.key IN (
            'naukri_receipt:'||j.requisition,'naukri_worker_receipt:'||j.requisition
        )) OR
        EXISTS (SELECT 1 FROM jobs prior JOIN application_packets a ON a.job_id=prior.id
            WHERE prior.source_platform='naukri' AND j.requisition IS NOT NULL
            AND substring(regexp_replace(prior.job_url,'[?#].*$','','') from '-([0-9]{10,20})/?$')=j.requisition
            AND a.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown')) OR
        EXISTS (SELECT 1 FROM owner_preferences p WHERE starts_with(p.key,'apply_work:')
            AND (p.value->>'job_id'=j.id::text OR (j.requisition IS NOT NULL AND p.value->>'requisition'=j.requisition))
            AND (p.value->>'stage' IN ('APPLYING','QUESTIONS','RESUME_ATTACHMENT','VERIFYING','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED','SUBMITTED_RECORDED')
                OR COALESCE(p.value->'admitted_actions','[]'::jsonb)<>'[]'::jsonb)) OR
        EXISTS (SELECT 1 FROM owner_preferences p WHERE starts_with(p.key,'gmail_application:')
            AND p.value->'confirmed_application'='true'::jsonb AND COALESCE(p.value->'deleted','false'::jsonb)<>'true'::jsonb
            AND p.value->>'expires_at'>to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
            AND (regexp_replace(p.value->>'job_url','[?#].*$','','') IN (
                regexp_replace(j.job_url,'[?#].*$','',''),regexp_replace(j.application_url,'[?#].*$','','')
            ) OR (NULLIF(p.value->>'job_url','') IS NULL AND lower(trim(p.value->>'company'))=lower(trim(c.name))
                  AND lower(trim(p.value->>'role'))=lower(trim(j.title))))) OR
        EXISTS (SELECT 1 FROM jobs other WHERE other.company_id=j.company_id AND other.status='applied') OR
        EXISTS (SELECT 1 FROM application_packets a JOIN jobs other ON other.id=a.job_id
            WHERE other.company_id=j.company_id AND a.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted'))
    ) IS NOT FALSE
) AS value
FROM saved j CROSS JOIN verified LEFT JOIN companies c ON c.id=j.company_id
)
SELECT jsonb_build_object('profile',(SELECT profile FROM verified),'jobs',COALESCE((SELECT jsonb_agg(value) FROM projected),'[]'::jsonb))
