# Separate Gmail compose constraint approval

The initial approved bundle committed once to project `luvdmwnlwaqgvfwlmlom`; its SHA-256 remains `2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e`. All 47 application tables, forced RLS, restricted grants and the preserved managed trigger passed live checks over the direct certificate-verified TLS endpoint. A restart persistence probe passed and was cleaned up. Existing credentials were retained.

Real secondary Gmail identity OAuth succeeded and its encrypted refresh token is stored in online Supabase. The compose upgrade exposed an inherited check constraint that permits `metadata` and `send` but rejects the existing backend's `compose` intent. The rejected insert rolled back; the connected identity remains valid.

Proposed separate file: [002_gmail_compose.sql](../../../supabase/fresh_public/followups/002_gmail_compose.sql).

SHA-256: `27c1a68eadbd916037effcf94580089777acdc1a66af68aaf9f706beb0cddf3d`.

Its only persistent effect is to replace `public.oauth_states.oauth_states_authorization_mode_check` with the same check allowing one additional value:

```sql
ALTER TABLE public.oauth_states
 DROP CONSTRAINT oauth_states_authorization_mode_check,
 ADD CONSTRAINT oauth_states_authorization_mode_check
 CHECK (authorization_mode IN ('metadata','send','compose'));
```

The full SQL wraps this in one transaction, uses 2-second lock and 30-second statement limits, and refuses any starting constraint other than the exact reviewed original on the application-owned table. Existing values are validated. It changes no rows, roles, credentials, RLS policies, grants, Google settings, Auth/Storage/Vault objects or managed triggers. It does not authorize sending. The original bundle, base catalog and historical migration checksums remain unchanged.

Actual disposable PostgreSQL 17 verification reproduced the original compose failure, then accepted metadata/send/compose, rejected an arbitrary mode, rejected replay, and rejected a missing constraint through the full catalog verifier. Test rows and injected faults were rolled back. The verifier accepts only the pinned original catalog or this exact follow-up state, including all existing permission and TLS checks.

Operator: `backend/scripts/phase1/apply_compose_followup.py`. It requires separate explicit owner approval, this exact checksum, exact project/direct endpoint and existing restricted-runtime preflight. It prompts for the existing administrator password privately, reserves a one-run marker, applies only this file, and verifies the result as the actual restricted login. It does not regenerate credentials or retry automatically.

Status: **prepared and tested; remote follow-up DDL not executed; separate owner approval required**. Gmail identity is connected; compose consent awaits this fix and a subsequent owner-completed Google browser flow. Sending remains disabled and no draft has been created.
