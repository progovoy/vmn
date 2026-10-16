"""The SQLite control plane (plan 25 F6): the F3 connection policy, a
cross-process atomic ``pop``, numbered schema steps and rowid-keeping upserts."""
import multiprocessing
import sqlite3

from vmn_exp.ui.control_plane import SQLiteControlPlane

KEYS = 300
STEPS = ["0002_identity.sql", "0003_audit.sql", "0006_control_plane_queries.sql"]


def _pop_all(path, start, results):
    cp = SQLiteControlPlane(path)
    start.wait()
    results.put([k for k in (f"s{i}" for i in range(KEYS)) if cp.pop("login", k, now=1) is not None])


def test_two_processes_popping_the_same_login_states_get_each_once(tmp_path):
    path = str(tmp_path / "cp.sqlite3")
    cp = SQLiteControlPlane(path)
    for i in range(KEYS):
        cp.put("login", f"s{i}", {"n": i}, expires_at=100)
    ctx = multiprocessing.get_context("spawn")
    start, results = ctx.Event(), ctx.Queue()
    procs = [ctx.Process(target=_pop_all, args=(path, start, results)) for _ in range(2)]
    for p in procs:
        p.start()
    start.set()
    got = [results.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(timeout=60)
    assert sorted(got[0] + got[1]) == sorted(f"s{i}" for i in range(KEYS))


def test_pop_of_an_expired_state_returns_none_and_deletes_it(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    cp.put("login", "s", {"n": 1}, expires_at=100)
    assert cp.pop("login", "s", now=150) is None
    assert cp.get("login", "s") is None


def test_the_file_uses_wal(tmp_path):
    path = str(tmp_path / "cp.sqlite3")
    SQLiteControlPlane(path)
    (mode,) = sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()
    assert mode == "wal"


def _applied(path):
    db = sqlite3.connect(path)
    return [n for (n,) in db.execute("SELECT name FROM vmn_schema_migrations ORDER BY name")]


def test_records_the_postgres_numbered_steps_it_applied(tmp_path):
    path = str(tmp_path / "cp.sqlite3")
    SQLiteControlPlane(path)
    assert _applied(path) == STEPS
    SQLiteControlPlane(path)  # reopening applies nothing twice
    assert _applied(path) == STEPS


def test_a_file_from_before_the_version_table_is_brought_forward(tmp_path):
    path = str(tmp_path / "cp.sqlite3")
    old = sqlite3.connect(path)
    # Workspaces, not tokens: 0006 drops pre-HMAC tokens by design.
    old.execute("CREATE TABLE vmn_workspaces (id TEXT PRIMARY KEY, doc TEXT NOT NULL)")
    old.execute("""INSERT INTO vmn_workspaces VALUES ('a', '{"id": "a"}')""")
    old.commit()
    old.close()
    cp = SQLiteControlPlane(path)
    assert _applied(path) == STEPS
    assert cp.list("workspace") == [{"id": "a"}]
    cp.put("audit", "e", {"x": 1})
    assert cp.get("audit", "e") == {"x": 1}


def test_overwriting_a_doc_keeps_its_place_in_the_listing(tmp_path):
    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    for key in ("a", "b", "c"):
        cp.put("token", key, {"id": key})
    cp.put("token", "a", {"id": "a", "revoked": True})
    assert [d["id"] for d in cp.list("token")] == ["a", "b", "c"]


def test_revoking_a_token_does_not_reorder_the_token_list(tmp_path):
    from vmn_exp.ui.auth.principal import VIEWER
    from vmn_exp.ui.auth.tokens import TokenService

    tokens = TokenService(SQLiteControlPlane(str(tmp_path / "cp.sqlite3")))
    ids = [tokens.create(name, {"ml": VIEWER})[1].id for name in ("one", "two", "three")]
    tokens.revoke(ids[0])
    assert [t.id for t in tokens.list()] == ids
