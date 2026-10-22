"""``vmn-exp ui diag``: fetch a diagnostic dump over HTTP (``--url``), have a
starved server write one on SIGUSR1 (``--pid``), or summarize a carried-out
dump (``--summarize``)."""
import json
import os
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.ui import diag_cli

DUMP = {"format": 1, "taken_at": "2026-10-22T10:00:00Z", "pid": 4242,
        "sections": {"pools": {"store-readers": {"max_workers": 4, "active": 4, "queued": 7}}}}


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _args(*argv):
    from version_stamp.cli.args import parse_user_commands

    return parse_user_commands(["ui", "diag", *argv])


def test_summarize_prints_an_existing_dump(tmp_path, capsys):
    path = tmp_path / "d.json"
    path.write_text(json.dumps(DUMP))
    assert diag_cli.handle_diag(_args("--summarize", str(path))) == 0
    out = capsys.readouterr().out
    assert "4242" in out and "store-readers" in out and "SATURATED" in out


def test_summarize_refuses_a_missing_or_broken_file(tmp_path):
    assert diag_cli.handle_diag(_args("--summarize", str(tmp_path / "none.json"))) == 1
    (tmp_path / "bad.json").write_text("{not json")
    assert diag_cli.handle_diag(_args("--summarize", str(tmp_path / "bad.json"))) == 1


@pytest.fixture
def server():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            if seen["auth"] != "Bearer sekret":
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps(DUMP).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", seen
    httpd.shutdown()
    httpd.server_close()


def test_url_fetches_writes_and_summarizes(server, tmp_path, capsys):
    url, seen = server
    out_file = tmp_path / "dump.json"
    assert diag_cli.handle_diag(_args("--url", url, "--token", "sekret", "-o", str(out_file))) == 0
    assert seen["path"] == "/api/v1/diag"
    assert json.loads(out_file.read_text()) == DUMP
    out = capsys.readouterr().out
    assert str(out_file) in out and "store-readers" in out


def test_url_takes_the_token_from_the_env_and_a_default_file_name(
        server, tmp_path, monkeypatch, capsys):
    url, seen = server
    monkeypatch.setenv("VMN_UI_TOKEN", "sekret")
    monkeypatch.chdir(tmp_path)
    assert diag_cli.handle_diag(_args("--url", url)) == 0
    assert seen["auth"] == "Bearer sekret"
    written = [p for p in os.listdir(tmp_path) if p.startswith("vmn-exp-diag-")]
    assert len(written) == 1 and written[0].endswith(".json")


def test_url_reports_an_http_error(server, tmp_path):
    url, _ = server
    assert diag_cli.handle_diag(_args("--url", url, "--token", "wrong",
                                      "-o", str(tmp_path / "d.json"))) == 1
    assert not (tmp_path / "d.json").exists()


FAKE_SERVER = textwrap.dedent("""
    import json, os, signal, sys, time
    diag_dir = os.path.join(sys.argv[1], "diag")
    def dump(*_):
        if sys.argv[2] == "ignore":
            return
        os.makedirs(diag_dir, exist_ok=True)
        path = os.path.join(diag_dir, f"diag-20261022T100001Z-{os.getpid()}.json")
        with open(path + ".tmp", "w") as f:
            json.dump(dict(json.loads(sys.argv[3]), pid=os.getpid()), f)
        os.replace(path + ".tmp", path)
    signal.signal(signal.SIGUSR1, dump)
    print("ready", flush=True)
    time.sleep(60)
""")


@pytest.fixture
def fake_server(tmp_path):
    procs = []

    def start(mode="dump"):
        proc = subprocess.Popen([sys.executable, "-c", FAKE_SERVER, str(tmp_path), mode,
                                 json.dumps(DUMP)], stdout=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == "ready"
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        proc.kill()
        proc.wait()


def test_pid_signals_and_waits_for_the_new_dump(fake_server, tmp_path, capsys):
    proc = fake_server()
    diag_dir = tmp_path / "diag"
    diag_dir.mkdir()
    old = diag_dir / f"diag-20200101T000000Z-{proc.pid}.json"
    old.write_text(json.dumps({"format": 1, "pid": "stale", "sections": {}}))
    assert diag_cli.handle_diag(_args("--pid", str(proc.pid), "--data-dir", str(tmp_path),
                                      "--wait", "10")) == 0
    out = capsys.readouterr().out
    assert f"diag-20261022T100001Z-{proc.pid}.json" in out
    assert "store-readers" in out and "stale" not in out


def test_pid_copies_the_dump_to_the_output_file(fake_server, tmp_path):
    proc = fake_server()
    dest = tmp_path / "out" / "copy.json"
    assert diag_cli.handle_diag(_args("--pid", str(proc.pid), "--data-dir", str(tmp_path),
                                      "-o", str(dest))) == 0
    assert json.loads(dest.read_text())["pid"] == proc.pid


def test_pid_times_out_when_no_dump_appears(fake_server, tmp_path):
    proc = fake_server("ignore")
    assert diag_cli.handle_diag(_args("--pid", str(proc.pid), "--data-dir", str(tmp_path),
                                      "--wait", "1")) == 1


def test_pid_reports_a_missing_process(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    assert diag_cli.handle_diag(_args("--pid", str(dead.pid), "--data-dir", str(tmp_path),
                                      "--wait", "1")) == 1


def test_needs_exactly_one_source():
    assert diag_cli.handle_diag(_args()) == 2
    assert diag_cli.handle_diag(_args("--pid", "1", "--url", "http://x")) == 2


def test_ui_dispatches_diag(monkeypatch):
    from vmn_exp.ui import cli

    monkeypatch.setattr(diag_cli, "handle_diag", lambda args: 7)
    assert cli.handle_ui(_args("--summarize", "x.json")) == 7
