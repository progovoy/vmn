"""``vmn-exp ui backup <path>`` (plan 25 F6): the SQLite control plane through
SQLite's online backup API, verified; Postgres prints the ``pg_dump`` command."""
import sqlite3
import threading

import pytest
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.ui import backup_cli
from vmn_exp.ui.control_plane import SQLiteControlPlane


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _args(*argv):
    from version_stamp.cli.args import parse_user_commands

    return parse_user_commands(["ui", "backup", *argv])


def test_the_backup_action_parses(tmp_path):
    assert _args(str(tmp_path / "b.db")).ui_args == ["backup", str(tmp_path / "b.db")]


def test_backup_during_writes_opens_verifies_and_holds_earlier_rows(tmp_path):
    src = str(tmp_path / "cp.sqlite3")
    cp = SQLiteControlPlane(src)
    for i in range(50):
        cp.put("audit", f"before{i}", {"i": i})
    stop = threading.Event()

    def write():
        n = 0
        while not stop.is_set():
            cp.put("audit", f"during{n}", {"n": n})
            n += 1

    writer = threading.Thread(target=write)
    writer.start()
    try:
        dest = str(tmp_path / "backup" / "cp.db")
        assert backup_cli.handle_backup(_args(dest, "--db", f"sqlite:///{src}")) == 0
    finally:
        stop.set()
        writer.join()
    copy = sqlite3.connect(dest)
    assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    ids = {i for (i,) in copy.execute("SELECT id FROM vmn_audit")}
    assert {f"before{i}" for i in range(50)} <= ids


def test_backup_defaults_to_the_data_dir_control_plane(tmp_path):
    data_dir = tmp_path / "ui"
    SQLiteControlPlane.in_data_dir(str(data_dir)).put("token", "a", {"id": "a"})
    dest = tmp_path / "b.db"
    assert backup_cli.handle_backup(_args(str(dest), "--data-dir", str(data_dir))) == 0
    assert sqlite3.connect(dest).execute("SELECT id FROM vmn_api_tokens").fetchall() == [("a",)]


def test_backup_refuses_a_missing_control_plane(tmp_path):
    dest = tmp_path / "b.db"
    assert backup_cli.handle_backup(_args(str(dest), "--data-dir", str(tmp_path / "none"))) == 1
    assert not dest.exists()


def test_backup_needs_exactly_one_path():
    assert backup_cli.handle_backup(_args()) == 2


def test_postgres_prints_the_pg_dump_command_without_the_password(capsys):
    dsn = "postgresql://vmn:s3cret@db.example:5433/vmnexp?sslmode=require"
    assert backup_cli.handle_backup(_args("/backups/cp.dump", "--db", dsn)) == 0
    out = capsys.readouterr().out
    assert out.strip() == (
        "pg_dump --host db.example --port 5433 --username vmn --dbname vmnexp"
        " --format custom --file /backups/cp.dump")
    assert "s3cret" not in out


def test_ui_dispatches_backup(tmp_path, monkeypatch):
    from vmn_exp.ui import cli

    monkeypatch.setattr(backup_cli, "handle_backup", lambda args: 7)
    assert cli.handle_ui(_args(str(tmp_path / "b.db"))) == 7
