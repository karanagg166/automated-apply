WITH inventory AS NOT MATERIALIZED (
 SELECT key,created_at,value::jsonb AS v FROM owner_preferences WHERE starts_with(key,'apply_work:')
), filtered AS NOT MATERIALIZED (
 SELECT * FROM inventory WHERE
 ($1::text IS NULL OR v->>'platform'=$1) AND ($2::text IS NULL OR v->>'stage'=$2) AND
 ($3::text IS NULL OR v->>'title' ILIKE $3 OR v->>'company' ILIKE $3 OR v->>'requisition' ILIKE $3 OR v->>'location' ILIKE $3) AND
 ($4::text IS NULL OR v->>'location' ILIKE $4) AND
 ($5::bigint IS NULL OR CASE WHEN jsonb_typeof(v->'match_score')='number' THEN (v->>'match_score')::numeric >= $5 ELSE false END)
), page AS (
 SELECT * FROM filtered ORDER BY created_at DESC,key OFFSET $6 LIMIT $7
), counts AS (
 SELECT coalesce(v->>'stage','UNKNOWN') AS stage,count(*) AS n FROM inventory GROUP BY 1
)
SELECT jsonb_build_object(
 'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
 'id',v->'id','platform',v->'platform','requisition',v->'requisition','url',v->'url',
 'stage',v->'stage','status',v->'status','operation',v->'operation','revision',v->'revision',
 'job_id',v->'job_id','packet_id',v->'packet_id','title',v->'title','company',v->'company',
 'location',v->'location','match_score',v->'match_score','attempts',v->'attempts',
 'reason',v->'reason','created_at',v->'created_at','updated_at',v->'updated_at',
 'submission_mode',v->'submission_mode','receipt_source',v->'receipt_source',
 'posted_at',v->'facts'->'posted_at','posted_date',v->'facts'->'posted_date',
 'applicants_min',v->'facts'->'applicants_min','applicants_max',v->'facts'->'applicants_max'
 ) ORDER BY created_at DESC,key),'[]'::jsonb) FROM page),
 'total',(SELECT count(*) FROM filtered),
 'counts',(SELECT coalesce(jsonb_object_agg(stage,n),'{}'::jsonb) FROM counts),
 'budget',(SELECT CASE WHEN jsonb_typeof(value::jsonb->'reservations')='array'
 THEN jsonb_build_object('used',jsonb_array_length(value::jsonb->'reservations'))
 ELSE jsonb_build_object('invalid',true) END FROM owner_preferences WHERE key=$8)
)
