-- Multi tenancy (plan 11 §6.3): orgs, membership, org_id on control-plane rows
-- and row-level security policies on every org-scoped table. The policies are
-- inert until ui/tenancy.py:enable_rls (tenancy: multi) turns RLS on; a
-- connection without app.org_id then sees no rows.
CREATE TABLE IF NOT EXISTS vmn_orgs (
    id bigserial PRIMARY KEY, name text NOT NULL, external_id text NOT NULL UNIQUE
);
-- Read before a request's org is known (the principal -> org lookup): no RLS.
CREATE TABLE IF NOT EXISTS vmn_memberships (
    org_id bigint NOT NULL REFERENCES vmn_orgs (id) ON DELETE CASCADE,
    principal text NOT NULL, role text NOT NULL,
    PRIMARY KEY (org_id, principal)
);

ALTER TABLE vmn_api_tokens ADD COLUMN IF NOT EXISTS org_id bigint NOT NULL DEFAULT 0;
ALTER TABLE vmn_sessions ADD COLUMN IF NOT EXISTS org_id bigint NOT NULL DEFAULT 0;
ALTER TABLE vmn_login_states ADD COLUMN IF NOT EXISTS org_id bigint NOT NULL DEFAULT 0;
ALTER TABLE vmn_workspaces ADD COLUMN IF NOT EXISTS org_id bigint NOT NULL DEFAULT 0;
ALTER TABLE vmn_audit ADD COLUMN IF NOT EXISTS org_id bigint NOT NULL DEFAULT 0;
-- Control-plane keys are unique per org.
ALTER TABLE vmn_api_tokens DROP CONSTRAINT IF EXISTS vmn_api_tokens_pkey;
ALTER TABLE vmn_api_tokens ADD PRIMARY KEY (org_id, id);
ALTER TABLE vmn_sessions DROP CONSTRAINT IF EXISTS vmn_sessions_pkey;
ALTER TABLE vmn_sessions ADD PRIMARY KEY (org_id, id);
ALTER TABLE vmn_login_states DROP CONSTRAINT IF EXISTS vmn_login_states_pkey;
ALTER TABLE vmn_login_states ADD PRIMARY KEY (org_id, id);
ALTER TABLE vmn_workspaces DROP CONSTRAINT IF EXISTS vmn_workspaces_pkey;
ALTER TABLE vmn_workspaces ADD PRIMARY KEY (org_id, id);
ALTER TABLE vmn_audit DROP CONSTRAINT IF EXISTS vmn_audit_pkey;
ALTER TABLE vmn_audit ADD PRIMARY KEY (org_id, id);

CREATE OR REPLACE FUNCTION vmn_current_org() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT coalesce(nullif(current_setting('app.org_id', true), '')::bigint, -1) $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['vmn_records', 'vmn_run_states', 'vmn_tombstones',
        'vmn_scope_gen', 'vmn_kv', 'vmn_api_tokens', 'vmn_sessions',
        'vmn_login_states', 'vmn_workspaces', 'vmn_audit']
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS vmn_org_isolation ON %I', t);
        EXECUTE format('CREATE POLICY vmn_org_isolation ON %I'
            ' USING (org_id = vmn_current_org()) WITH CHECK (org_id = vmn_current_org())', t);
    END LOOP;
END $$;
