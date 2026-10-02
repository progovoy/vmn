-- Control-plane identity tables: never truncated (plan 11 I7).
CREATE TABLE IF NOT EXISTS vmn_api_tokens (
    id text PRIMARY KEY, doc jsonb NOT NULL, created bigserial
);
CREATE TABLE IF NOT EXISTS vmn_sessions (
    id text PRIMARY KEY, doc jsonb NOT NULL, expires_at double precision NOT NULL,
    created bigserial
);
CREATE TABLE IF NOT EXISTS vmn_login_states (
    id text PRIMARY KEY, doc jsonb NOT NULL, expires_at double precision NOT NULL,
    created bigserial
);
