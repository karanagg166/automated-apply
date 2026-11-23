SELECT jsonb_build_object(
    'at', clock_timestamp(),
    'selection', selected.value,
    'pin', pin.value,
    'profile', profile.value,
    'account', account.value
)
FROM (SELECT 'chr_selection' AS key) requested
LEFT JOIN owner_preferences selected ON selected.key = requested.key
LEFT JOIN owner_preferences pin ON pin.key = 'chr_fixed_profile'
LEFT JOIN owner_preferences profile ON profile.key = 'chr_prof:' || (selected.value->>'profile_binding_id')
LEFT JOIN owner_preferences account ON account.key = 'naukri_account_binding'
