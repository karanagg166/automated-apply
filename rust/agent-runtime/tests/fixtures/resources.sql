-- Fictional inspection inventory; no owner data, schema or application grants.
DROP TABLE IF EXISTS candidate_resources;
CREATE TABLE candidate_resources (
    id uuid PRIMARY KEY,candidate_profile_id uuid NOT NULL,resource_type text NOT NULL,
    label text NOT NULL,url text NOT NULL,user_confirmed boolean NOT NULL,
    is_primary boolean NOT NULL,source_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00Z',
    updated_at timestamptz NOT NULL DEFAULT '2026-11-14T00:00:00.000007Z',
    UNIQUE(candidate_profile_id,resource_type,url)
);
CREATE UNIQUE INDEX fixture_resource_primary ON candidate_resources(candidate_profile_id,resource_type) WHERE is_primary;
INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type)
VALUES ('10000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','resume',' Fictional résumé 🚀 ','private-resume:20000000-0000-0000-0000-000000000001',true,true,'private_upload'),
('10000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000099','resume','Foreign profile resume','https://example.com/foreign',true,true,'user');
