-- Plan 25 F5: indexed control-plane queries, HMAC tokens, org-scoped search rows.

-- Credential ids are random, so unique across orgs: auth looks them up by id
-- alone before any org is bound.
CREATE UNIQUE INDEX IF NOT EXISTS vmn_api_tokens_id ON vmn_api_tokens (id);
CREATE UNIQUE INDEX IF NOT EXISTS vmn_sessions_id ON vmn_sessions (id);
CREATE UNIQUE INDEX IF NOT EXISTS vmn_login_states_id ON vmn_login_states (id);
-- The expiry sweep.
CREATE INDEX IF NOT EXISTS vmn_sessions_expires ON vmn_sessions (org_id, expires_at);
CREATE INDEX IF NOT EXISTS vmn_login_states_expires ON vmn_login_states (org_id, expires_at);
-- Audit pages, newest first.
CREATE INDEX IF NOT EXISTS vmn_audit_created ON vmn_audit (org_id, created);

-- Token secrets are HMAC-SHA256 under a server key now: scrypt hashes can't verify.
DELETE FROM vmn_api_tokens;

-- Server-wide secrets (the token HMAC key), never org-scoped.
CREATE TABLE IF NOT EXISTS vmn_settings (k text PRIMARY KEY, v text NOT NULL);

-- Search rows are derived: rebuilt with the org they belong to.
DROP TABLE IF EXISTS vmn_search_rows;
CREATE TABLE vmn_search_rows (
    org_id bigint NOT NULL DEFAULT 0,
    workspace text NOT NULL, app text NOT NULL, verstr text NOT NULL,
    pos integer NOT NULL, data jsonb NOT NULL,
    PRIMARY KEY (org_id, workspace, app, verstr)
);
CREATE INDEX vmn_search_rows_order ON vmn_search_rows (org_id, workspace, app, pos);
CREATE POLICY vmn_org_isolation ON vmn_search_rows
    USING (org_id = vmn_current_org()) WITH CHECK (org_id = vmn_current_org());

-- Cache deltas read tombstones past a generation.
CREATE INDEX IF NOT EXISTS vmn_tombstones_seq ON vmn_tombstones (org_id, workspace_id, app, seq);
