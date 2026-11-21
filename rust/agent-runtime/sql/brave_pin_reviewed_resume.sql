SELECT d.sha256
FROM candidate_profiles p
JOIN owner_preferences confirmation
  ON confirmation.key = 'phase1_profile_confirmation'
  AND confirmation.value->>'profile_id' = p.id::text
  AND confirmation.value->'profile_version' = to_jsonb(p.version)
  AND confirmation.value->>'confirmed_at' IS NOT NULL
JOIN candidate_resources r
  ON r.candidate_profile_id = p.id
  AND r.resource_type = 'resume'
  AND r.source_type = 'private_upload'
  AND r.user_confirmed AND r.is_primary
JOIN private_resumes d ON d.resource_id = r.id
  AND r.url = 'private-resume:' || d.id::text AND d.confirmed
WHERE p.singleton_key = 'primary' AND p.id = $1 AND p.version = $2
LIMIT 2
