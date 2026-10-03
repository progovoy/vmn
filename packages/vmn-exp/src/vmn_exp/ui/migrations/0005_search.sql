-- Cross-workspace search (plan 11 §4.4): every watched app's derived rows as
-- jsonb, so GET /api/v1/search filters with the query language compiled to SQL.
CREATE TABLE IF NOT EXISTS vmn_search_rows (
    workspace text NOT NULL, app text NOT NULL, verstr text NOT NULL,
    pos integer NOT NULL, data jsonb NOT NULL,
    PRIMARY KEY (workspace, app, verstr)
);
CREATE INDEX IF NOT EXISTS vmn_search_rows_order ON vmn_search_rows (workspace, app, pos);
