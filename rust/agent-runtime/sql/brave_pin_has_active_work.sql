SELECT EXISTS (
    SELECT 1 FROM owner_preferences
    WHERE
        (starts_with(key, 'apply_work:') AND (
            coalesce(value->>'status', '') IN ('leased', 'executing')
            OR (value->'form_pending' = 'true'::jsonb
                AND coalesce(value->>'stage', '') NOT IN
                    ('SUBMISSION_UNKNOWN', 'SUBMITTED_RECORDED', 'SUBMITTED_CONFIRMED', 'FAILED_FINAL', 'SKIPPED'))
        ))
        OR (starts_with(key, 'chr_cmd:') AND coalesce(value->>'state', '') NOT IN
            ('completed', 'failed', 'expired', 'cancelled', 'outcome_unknown'))
        OR (starts_with(key, 'fill_plan:') AND value->>'state' IN ('preview', 'authorized'))
        OR (starts_with(key, 'ext_task:') AND coalesce(value->>'state', '') NOT IN
            ('PAUSED', 'FAILED_FINAL', 'SUBMISSION_UNKNOWN', 'SUBMITTED_CONFIRMED'))
        OR (starts_with(key, 'ext_task:') AND value->>'state' = 'PAUSED'
            AND (value->>'plan_id' IS NOT NULL OR value->>'authorization_id' IS NOT NULL))
)
