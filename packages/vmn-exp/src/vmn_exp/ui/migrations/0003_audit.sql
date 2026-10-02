-- Control-plane tables: never truncated (plan 11 I7).
CREATE TABLE IF NOT EXISTS vmn_workspaces (
    id text PRIMARY KEY, doc jsonb NOT NULL, created bigserial
);
CREATE TABLE IF NOT EXISTS vmn_audit (
    id text PRIMARY KEY, doc jsonb NOT NULL, created bigserial
);
