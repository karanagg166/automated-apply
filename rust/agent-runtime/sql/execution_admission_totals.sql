-- Aggregate only durable admissions. Never transfer full listing/packet/history payloads.
-- Malformed admission arrays or entries fail closed; missing bytes cannot become a refund.
WITH works AS (
 SELECT key,value::jsonb AS v FROM owner_preferences WHERE starts_with(key,'apply_work:')
 AND (value->>'platform'=$1 OR value->>'platform' IS NULL)
), expanded AS (
 SELECT key,v,a,CASE WHEN jsonb_typeof(a->'at')='string'
 AND (a->>'at') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$'
 AND pg_input_is_valid(a->>'at','timestamp with time zone') THEN (a->>'at')::timestamptz END AS admitted_at
 FROM works LEFT JOIN LATERAL jsonb_array_elements(
 CASE WHEN jsonb_typeof(v->'admitted_actions')='array' THEN v->'admitted_actions' ELSE '[]'::jsonb END
 ) AS elements(a) ON true
), per_work AS (
 SELECT key,bool_or(v->>'platform' IS NULL OR NOT coalesce(pg_input_is_valid(v->>'id','uuid'),false)
 OR key!='apply_work:'||(v->>'id') OR coalesce(jsonb_typeof(v->'admitted_actions'),'missing')!='array'
 OR (a IS NOT NULL AND (jsonb_typeof(a)!='object' OR coalesce(jsonb_typeof(a->'fingerprint'),'missing')!='string'
 OR NOT coalesce((a->>'fingerprint') ~ '^(apply|answer|upload_resume|answer_questionnaire):.+$',false)
 OR admitted_at IS NULL OR admitted_at>$2))) AS invalid,
 coalesce(bool_or(starts_with(a->>'fingerprint','apply:')),false) AS applied,
 coalesce(bool_or(admitted_at BETWEEN $2::timestamptz-interval '1 hour' AND $2),false) AS recent
 FROM expanded GROUP BY key
)
SELECT jsonb_build_object('invalid',coalesce(bool_or(invalid),false),
 'lifetime_apply',count(*) FILTER(WHERE applied),'hourly_work',count(*) FILTER(WHERE recent)) FROM per_work
