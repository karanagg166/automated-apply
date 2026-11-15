-- One coherent, bounded status statement. Closed history never occupies active inventory.
SELECT jsonb_build_object(
 'at',clock_timestamp(),
 'selection',coalesce((SELECT value FROM owner_preferences WHERE key='chr_selection'),'{"version":0,"profile_binding_id":null}'::jsonb),
 'profiles',coalesce((SELECT jsonb_agg(value ORDER BY created_at,key) FROM
   (SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'chr_prof:') ORDER BY created_at,key LIMIT 9) p),'[]'::jsonb),
 'active_tasks',coalesce((SELECT jsonb_agg(identity) FROM
   (SELECT DISTINCT coalesce(value->'profile_binding_id','null'::jsonb) AS identity FROM owner_preferences
    WHERE starts_with(key,'ext_task:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('PAUSED','FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')) LIMIT 10001) t),'[]'::jsonb),
 'active_commands',coalesce((SELECT jsonb_agg(jsonb_build_object('profile_binding_id',value->'profile_binding_id','expires_at',value->'expires_at')) FROM
   (SELECT value FROM owner_preferences WHERE starts_with(key,'chr_cmd:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown')) LIMIT 10001) a),'[]'::jsonb),
 'commands',coalesce((SELECT jsonb_agg(value-'lease_token'-'payload_hash' ORDER BY created_at,key) FROM
   (SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'chr_cmd:') ORDER BY created_at DESC,key DESC LIMIT 30) c),'[]'::jsonb),
 'receipts',coalesce((SELECT jsonb_agg(value ORDER BY created_at,key) FROM
   (SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'ext_receipt:') ORDER BY created_at DESC,key DESC LIMIT 30) r),'[]'::jsonb)
)
