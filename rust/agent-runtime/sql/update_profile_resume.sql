UPDATE candidate_profiles SET
full_name=($1::jsonb->>'full_name'),email=($1::jsonb->>'email'),phone=($1::jsonb->>'phone'),
linkedin_url=($1::jsonb->>'linkedin_url'),github_url=($1::jsonb->>'github_url'),
portfolio_url=($1::jsonb->>'portfolio_url'),personal_website=($1::jsonb->>'personal_website'),
verified_experience_years=($1::jsonb->>'verified_experience_years')::double precision,
verified_skills=$1::jsonb->'verified_skills',verified_roles=$1::jsonb->'verified_roles',
education=$1::jsonb->'education',projects=$1::jsonb->'projects',certifications=$1::jsonb->'certifications',
summary=($1::jsonb->>'summary'),preferences=$1::jsonb->'preferences',
active_resume_version_id=$4,version=version+1,updated_at=clock_timestamp()
WHERE id=$2 AND singleton_key='primary' AND version=$3
