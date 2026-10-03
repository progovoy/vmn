"""Row-level security in multi tenancy (plan 11 §6.3)."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.ui import migrations, tenancy  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresControlPlane, PostgresStore  # noqa: E402


@pytest.fixture
def app_dsn(pg_dsn):
    """A non-superuser DSN (superusers bypass RLS) on a migrated, RLS-on DB."""
    role = f"r_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        migrations.apply_migrations(conn)
        tenancy.enable_rls(conn)
        conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'x'")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}")
        conn.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role}")
    yield pg_dsn.replace("postgres:x@", f"{role}:x@")
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(f"DROP OWNED BY {role}")
        conn.execute(f"DROP ROLE {role}")


def test_cache_rows_are_isolated_per_org(app_dsn):
    PostgresStore(app_dsn, org_id=1).save((1, "app"), {"a": {"verstr": "1"}}, set())
    PostgresStore(app_dsn, org_id=2).save((1, "app"), {"b": {"verstr": "2"}}, set())
    assert set(PostgresStore(app_dsn, org_id=1).load((1, "app"))) == {"a"}
    assert set(PostgresStore(app_dsn, org_id=2).load((1, "app"))) == {"b"}


def test_control_plane_rows_are_isolated_per_org(app_dsn):
    PostgresControlPlane(app_dsn, org_id=1).put("workspace", "w", {"name": "w"})
    assert PostgresControlPlane(app_dsn, org_id=2).get("workspace", "w") is None
    assert PostgresControlPlane(app_dsn, org_id=2).list("workspace") == []
    assert PostgresControlPlane(app_dsn, org_id=1).get("workspace", "w") == {"name": "w"}


def test_connection_without_org_sees_zero_rows(app_dsn):
    PostgresStore(app_dsn, org_id=1).save((1, "app"), {"a": {"verstr": "1"}}, set())
    PostgresControlPlane(app_dsn, org_id=1).put("workspace", "w", {"name": "w"})
    with psycopg.connect(app_dsn, autocommit=True) as conn:
        for table in ("vmn_records", "vmn_scope_gen", "vmn_workspaces"):
            (n,) = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert n == 0, table


def test_rls_is_forced_on_every_org_table(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        migrations.apply_migrations(conn)
        tenancy.enable_rls(conn)
        rows = conn.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = ANY(%s)", (list(tenancy.RLS_TABLES),)
        ).fetchall()
    assert {r[0] for r in rows} == set(tenancy.RLS_TABLES)
    assert all(r[1] and r[2] for r in rows)


def test_orgs_and_membership_resolve_a_principal_org(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        migrations.apply_migrations(conn)
        org = tenancy.create_org(conn, "acme")
        tenancy.add_member(conn, org.id, "oidc:alice", "admin")
        assert tenancy.org_of(conn, "oidc:alice") == org.id
        assert tenancy.org_of(conn, "oidc:bob") is None
        assert org.external_id and tenancy.create_org(conn, "b").external_id != org.external_id
