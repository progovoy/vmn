#!/usr/bin/env python3
"""``vmn-exp ui backup <path> [--config server.yml | --db <dsn> | --data-dir]``
(plan 25 F6).

A SQLite control plane is copied through SQLite's online backup API (safe
while the server writes), and the copy is opened and integrity-checked. A
Postgres one is the operator's ``pg_dump``: the command is printed, with the
DSN's host/port/user/database and never its password.
"""
import os
import shlex
import sqlite3
from urllib.parse import unquote, urlparse

from version_stamp.api import VMN_LOGGER
from vmn_exp.core import sqlite_conn


def _control_plane_db(args):
    """``("postgres", dsn)`` or ``("sqlite", path)`` of the invocation."""
    from vmn_exp.ui.cli import DEFAULT_DATA_DIR, postgres_dsn
    from vmn_exp.ui.config import resolve_config
    from vmn_exp.ui.control_plane import CONTROL_PLANE_FILE

    cfg = resolve_config(args)
    dsn = postgres_dsn(cfg)
    if dsn:
        return "postgres", dsn
    if cfg is not None and cfg.db and cfg.db.startswith("sqlite:///"):
        return "sqlite", cfg.db[len("sqlite:///"):]
    data_dir = cfg.data_dir if cfg is not None else args.data_dir or DEFAULT_DATA_DIR
    return "sqlite", os.path.join(data_dir, CONTROL_PLANE_FILE)


def pg_dump_command(dsn, dest):
    url = urlparse(dsn)
    parts = ["pg_dump"]
    for flag, value in (("--host", url.hostname), ("--port", url.port),
                        ("--username", url.username), ("--dbname", url.path.lstrip("/"))):
        if value:
            parts += [flag, shlex.quote(unquote(str(value)))]
    return " ".join(parts + ["--format", "custom", "--file", shlex.quote(dest)])


def backup_sqlite(src_path, dest):
    """Copy *src_path* to *dest* online; ``True`` once the copy verifies."""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    src = sqlite_conn.connect(src_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            # One self-contained file: no -wal/-shm beside the copy.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()
    copy = sqlite_conn.connect(dest, readonly=True)
    try:
        return copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        copy.close()


def handle_backup(args):
    rest = list(args.ui_args[1:])
    if len(rest) != 1:
        VMN_LOGGER.error("usage: vmn-exp ui backup <path> [--config server.yml | --db <dsn>]")
        return 2
    dest = rest[0]
    kind, source = _control_plane_db(args)
    if kind == "postgres":
        print(pg_dump_command(source, dest))
        return 0
    if not os.path.exists(source):
        VMN_LOGGER.error(f"No control plane at {source}")
        return 1
    if not backup_sqlite(source, dest):
        VMN_LOGGER.error(f"The backup at {dest} failed its integrity check")
        return 1
    VMN_LOGGER.info(f"Backed up {source} to {dest} (integrity_check ok)")
    return 0
