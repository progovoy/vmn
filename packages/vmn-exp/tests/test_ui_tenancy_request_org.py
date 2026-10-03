"""Multi tenancy binds the org per request, per transaction (plan 11 §6.3):
one shared store serves every org, and no org outlives its transaction."""
import uuid

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.ui import tenancy  # noqa: E402
from vmn_exp.ui.tenancy import org_context  # noqa: E402


@pytest.fixture
def app_dsn(pg_dsn):
    """A non-superuser DSN (superusers bypass RLS) on a migrated, RLS-on DB."""
    import psycopg

    from vmn_exp.ui import migrations

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


def test_one_control_plane_serves_each_request_org(app_dsn):
    from vmn_exp.ui.control_plane_pg import PostgresControlPlane

    cp = PostgresControlPlane(app_dsn)
    for org in (1, 2):
        with org_context(org):
            cp.put("workspace", "w", {"name": f"w{org}"})
    for org in (1, 2):
        with org_context(org):
            assert cp.get("workspace", "w") == {"name": f"w{org}"}
            assert cp.list("workspace") == [{"name": f"w{org}"}]


def test_the_org_setting_does_not_outlive_its_transaction(app_dsn):
    from vmn_exp.ui.control_plane_pg import PostgresControlPlane

    cp = PostgresControlPlane(app_dsn)
    with org_context(1):
        cp.put("workspace", "w", {"name": "w"})
    (value,) = cp._db.execute("SELECT current_setting('app.org_id', true)").fetchone()
    assert value in (None, "")


def test_cache_store_follows_the_request_org(app_dsn):
    from vmn_exp.ui.cache_pg import PostgresStore

    store = PostgresStore(app_dsn)
    with org_context(1):
        store.save((1, "app"), {"a": {"verstr": "1"}}, set())
    with org_context(2):
        assert store.load((1, "app")) == {}
    with org_context(1):
        assert set(store.load((1, "app"))) == {"a"}


class _Principal:
    def __init__(self, org_id):
        self.org_id = org_id


def _app(tenancy_mode, org_id):
    app = FastAPI()
    tenancy.install_org_middleware(app, tenancy_mode)

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = _Principal(org_id)
        return await call_next(request)

    @app.get("/org")
    def org():
        return {"org": tenancy.current_org()}

    return TestClient(app)


def test_middleware_binds_the_principal_org_for_the_request():
    assert _app("multi", 7).get("/org").json() == {"org": 7}
    assert tenancy.current_org() is None


def test_single_tenancy_binds_no_org():
    assert _app("single", 7).get("/org").json() == {"org": None}
