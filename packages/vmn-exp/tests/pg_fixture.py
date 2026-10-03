"""Throwaway Postgres for tests: ``pg_dsn`` is a fresh database per test.

Reuses ``VMN_TEST_PG_DSN`` when set, else starts one ``postgres:16`` container
per test session (per xdist worker). Skips cleanly without psycopg or docker.
"""
import os
import shutil
import subprocess
import time
import uuid

import pytest

_IMAGE = "postgres:16"
_PASSWORD = "x"


def _docker(*args):
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _wait_ready(psycopg, dsn, timeout=60):
    deadline = time.time() + timeout
    while True:
        try:
            psycopg.connect(dsn, connect_timeout=2).close()
            return
        except psycopg.OperationalError:
            if time.time() > deadline:
                raise
            time.sleep(0.5)


def _start_container():
    if shutil.which("docker") is None:
        pytest.skip("docker unavailable")
    try:
        cid = _docker(
            "run", "-d", "--rm", "-p", "0:5432", "-e", f"POSTGRES_PASSWORD={_PASSWORD}", _IMAGE
        )
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"cannot start postgres container: {exc.stderr}")
    port = _docker("port", cid, "5432/tcp").splitlines()[0].rsplit(":", 1)[1]
    return cid, f"postgresql://postgres:{_PASSWORD}@127.0.0.1:{port}/postgres"


@pytest.fixture(scope="session")
def pg_server_dsn():
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ.get("VMN_TEST_PG_DSN")
    if dsn:
        yield dsn
        return
    cid, dsn = _start_container()
    try:
        _wait_ready(psycopg, dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


@pytest.fixture
def pg_dsn(pg_server_dsn):
    import psycopg

    name = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    yield pg_server_dsn.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def pg_rls_dsn(pg_dsn):
    """A non-superuser DSN (superusers bypass RLS) on a migrated, RLS-on DB."""
    import psycopg

    from vmn_exp.ui import migrations, tenancy

    role = f"r_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        migrations.apply_migrations(conn)
        tenancy.enable_rls(conn)
        conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'x'")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}")
        conn.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role}")
        conn.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {role}")
    yield pg_dsn.replace("postgres:x@", f"{role}:x@")
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(f"DROP OWNED BY {role}")
        conn.execute(f"DROP ROLE {role}")
