"""Postgres control-plane queries at scale (plan 25 F5): indexed credential
lookups, the expiry sweep and SQL audit pages."""
import json

import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.ui.control_plane_pg import PostgresControlPlane  # noqa: E402

CREDENTIALS = ("vmn_sessions", "vmn_api_tokens", "vmn_login_states")


def _fill(dsn, table, n, expires_at=None):
    expiring = table != "vmn_api_tokens"
    cols = "org_id, id, doc" + (", expires_at" if expiring else "")
    vals = "g % 3, 'id' || g, '{}'::jsonb" + (f", {expires_at}" if expiring else "")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"INSERT INTO {table} ({cols}) SELECT {vals}"
                     f" FROM generate_series(1, {n}) g")
        conn.execute(f"ANALYZE {table}")


def _plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", ()):
        yield from _plan_nodes(child)


def _explain(dsn, sql, args, analyze=False):
    opts = "ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON"
    with psycopg.connect(dsn, autocommit=True) as conn:
        (doc,) = conn.execute(f"EXPLAIN ({opts}) {sql}", args).fetchone()
    doc = doc if isinstance(doc, list) else json.loads(doc)
    return list(_plan_nodes(doc[0]["Plan"]))


@pytest.fixture
def cp(pg_dsn):
    store = PostgresControlPlane(pg_dsn)
    store.list("workspace")  # migrated
    return store


@pytest.mark.parametrize("table", CREDENTIALS)
def test_credential_lookup_uses_the_id_index(pg_dsn, cp, table):
    _fill(pg_dsn, table, 20_000, expires_at=10**12)
    nodes = _explain(pg_dsn, PostgresControlPlane.CREDENTIAL_SQL.format(table=table), ("id77",))
    assert not [n for n in nodes if n["Node Type"] == "Seq Scan"]
    assert {n.get("Index Name") for n in nodes} & {f"{table}_id"}


def test_one_sweep_removes_every_expired_credential(pg_dsn, cp):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:  # _fill's orgs 1 and 2
        conn.execute("INSERT INTO vmn_orgs (id, name, external_id)"
                     " VALUES (1, 'a', 'x1'), (2, 'b', 'x2')")
    _fill(pg_dsn, "vmn_sessions", 200_000, expires_at=100)
    _fill(pg_dsn, "vmn_login_states", 1_000, expires_at=100)
    cp.put("session", "live", {"ok": 1}, expires_at=300)
    cp.sweep_expired(now=200)
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        left = conn.execute("SELECT id FROM vmn_sessions").fetchall()
        (logins,) = conn.execute("SELECT count(*) FROM vmn_login_states").fetchone()
    assert left == [("live",)] and logins == 0


def test_an_audit_page_reads_only_its_rows(pg_dsn, cp):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO vmn_audit (org_id, id, doc) SELECT 0,"
                     " lpad(g::text, 20, '0'), jsonb_build_object('i', g)"
                     " FROM generate_series(1, 20000) g")
        conn.execute("ANALYZE vmn_audit")
    nodes = _explain(pg_dsn, PostgresControlPlane.PAGE_SQL.format(table="vmn_audit"),
                     (0, 10, 20), analyze=True)
    scans = [n for n in nodes if "Scan" in n["Node Type"]]
    assert [(n["Node Type"], n["Scan Direction"]) for n in scans] == [("Index Scan", "Backward")]
    assert scans[0]["Index Name"] == "vmn_audit_created"
    assert scans[0]["Actual Rows"] <= 30
    assert [d["i"] for d in cp.page("audit", offset=20, limit=3)] == [19980, 19979, 19978]
    assert cp.count("audit") == 20_000


def test_replicas_popping_one_login_state_get_it_once(pg_dsn, cp):
    import threading

    keys = [f"s{i}" for i in range(200)]
    for key in keys:
        cp.put("login", key, {"k": key}, expires_at=10**12)
    replicas = [PostgresControlPlane(pg_dsn) for _ in range(4)]
    got = []
    start = threading.Barrier(len(replicas))

    def pop_all(replica):
        start.wait()
        got.extend(d["k"] for d in (replica.pop("login", k, now=0) for k in keys) if d)

    threads = [threading.Thread(target=pop_all, args=(r,)) for r in replicas]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(got) == sorted(keys)


def test_the_migration_drops_existing_tokens(pg_dsn, cp):
    from vmn_exp.ui import migrations

    _fill(pg_dsn, "vmn_api_tokens", 3)
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM vmn_schema_migrations WHERE name LIKE '0006_%'")
        assert [n for n in migrations.apply_migrations(conn) if n.startswith("0006_")]
        (n,) = conn.execute("SELECT count(*) FROM vmn_api_tokens").fetchone()
    assert n == 0


def test_tombstones_are_indexed_by_scope_and_seq(pg_dsn, cp):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        (defn,) = conn.execute("SELECT indexdef FROM pg_indexes"
                               " WHERE indexname = 'vmn_tombstones_seq'").fetchone()
    assert "(org_id, workspace_id, app, seq)" in defn
