-- Derived cache tables (plan 11 §4.2): TRUNCATEd on a cache schema change.
CREATE TABLE IF NOT EXISTS vmn_cache_meta (k text PRIMARY KEY, v text);

CREATE TABLE IF NOT EXISTS vmn_records (
    org_id bigint NOT NULL DEFAULT 0, workspace_id bigint NOT NULL DEFAULT 0,
    app text NOT NULL, key text NOT NULL,
    data jsonb NOT NULL, seq bigint NOT NULL,
    PRIMARY KEY (org_id, workspace_id, app, key)
);
CREATE INDEX IF NOT EXISTS vmn_records_seq ON vmn_records (org_id, workspace_id, app, seq);

CREATE TABLE IF NOT EXISTS vmn_run_states (
    org_id bigint NOT NULL DEFAULT 0, workspace_id bigint NOT NULL DEFAULT 0,
    app text NOT NULL, key text NOT NULL,
    data jsonb NOT NULL, seq bigint NOT NULL,
    PRIMARY KEY (org_id, workspace_id, app, key)
);
CREATE INDEX IF NOT EXISTS vmn_run_states_seq ON vmn_run_states (org_id, workspace_id, app, seq);

CREATE TABLE IF NOT EXISTS vmn_tombstones (
    org_id bigint NOT NULL DEFAULT 0, workspace_id bigint NOT NULL DEFAULT 0,
    app text NOT NULL, key text NOT NULL,
    seq bigint NOT NULL, ts double precision NOT NULL,
    PRIMARY KEY (org_id, workspace_id, app, key)
);

CREATE TABLE IF NOT EXISTS vmn_scope_gen (
    org_id bigint NOT NULL DEFAULT 0, workspace_id bigint NOT NULL DEFAULT 0,
    app text NOT NULL,
    gen bigint NOT NULL, horizon bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, workspace_id, app)
);

CREATE TABLE IF NOT EXISTS vmn_kv (
    org_id bigint NOT NULL DEFAULT 0, workspace_id bigint NOT NULL DEFAULT 0,
    scope text NOT NULL, fingerprint text NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY (org_id, workspace_id, scope)
);
