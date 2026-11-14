-- Fictional saved prose only; no owner account, sending or submission permissions.
DROP TABLE IF EXISTS application_answer_drafts;
CREATE TABLE application_answer_drafts (
 id uuid PRIMARY KEY,candidate_profile_id uuid NOT NULL,job_id uuid,
 question text NOT NULL,answer text NOT NULL,question_category text NOT NULL,writing_style text NOT NULL,
 provider text,model text,evidence_references jsonb NOT NULL,candidate_profile_version integer NOT NULL,
 review_status text NOT NULL,created_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z',updated_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z'
);
INSERT INTO application_answer_drafts(id,candidate_profile_id,question,answer,question_category,writing_style,evidence_references,candidate_profile_version,review_status)
VALUES ('30000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',' Describe   work ',' I built fictional Rust workers. ','project_explanation','professional','[{"source_type":"verified_project","source_id":"fixture:project:0"}]',4,'draft'),
('30000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000002','Older profile answer','Previously approved fixture text','short_text','concise','[]',3,'reviewed'),
('30000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000099','Foreign profile question','Foreign private fixture answer','short_text','concise','[]',4,'draft');
