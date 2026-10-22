"""The diagnostic dump: a registry of sections, each failure contained, and
nothing secret ever in it."""
import json
import os
import threading

import pytest

from vmn_exp.ui import diag
from vmn_exp.ui.diag import registry
from vmn_exp.ui.diag.redact import redact_uri

DEFAULT_SECTIONS = {"threads", "requests", "pools", "indexes", "process", "env"}


@pytest.fixture(autouse=True)
def _isolated_sections(monkeypatch):
    monkeypatch.setattr(registry, "_SECTIONS", dict(registry._SECTIONS))
    monkeypatch.setattr(registry, "_SECRETS", set(registry._SECRETS))


def test_build_dump_has_its_header_and_every_default_section():
    diag.install_default_sections()
    dump = diag.build_dump()
    assert dump["format"] == 1
    assert dump["pid"] == os.getpid()
    assert dump["taken_at"].endswith("Z")
    assert DEFAULT_SECTIONS <= set(dump["sections"])
    json.dumps(dump)  # one JSON file


def test_a_raising_section_reports_its_error_and_the_rest_survive():
    def broken():
        raise RuntimeError("boom")

    diag.register_section("broken", broken)
    diag.register_section("fine", lambda: {"ok": 1})
    sections = diag.build_dump()["sections"]
    assert "boom" in sections["broken"]["error"]
    assert sections["fine"] == {"ok": 1}


def test_threads_collapse_identical_stacks_with_a_count():
    release = threading.Event()

    def park():
        release.wait(10)

    workers = [threading.Thread(target=park, name=f"parked-{i}", daemon=True)
               for i in range(5)]
    for t in workers:
        t.start()
    try:
        section = diag.threads_section()
    finally:
        release.set()
        for t in workers:
            t.join(5)
    assert section["count"] >= 6
    parked = [g for g in section["groups"]
              if any(t["name"].startswith("parked-") for t in g["threads"])]
    assert len(parked) == 1
    group = parked[0]
    assert group["count"] == 5
    assert {"name", "ident", "daemon"} <= set(group["threads"][0])
    assert any("park" in line for line in group["stack"])


def test_env_lists_names_only(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI-very-secret")
    monkeypatch.setenv("VMN_EXPERIMENT_STORE", "s3://bkt/p")
    monkeypatch.setenv("UNRELATED_VAR", "x")
    names = diag.env_section()["set"]
    assert "AWS_SECRET_ACCESS_KEY" in names and "VMN_EXPERIMENT_STORE" in names
    assert "UNRELATED_VAR" not in names
    assert "wJalrXUtnFEMI" not in json.dumps(diag.env_section())


def test_the_dump_never_carries_an_aws_secret_from_the_env(monkeypatch):
    secret = "wJalrXUtnFEMI-K7MDENG-bPxRfiCY"
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret)
    diag.install_default_sections()
    diag.register_section("leaky", lambda: {"oops": f"key={secret}"})
    assert secret not in json.dumps(diag.build_dump())


def test_the_dump_never_carries_a_registered_secret():
    diag.add_secret("t0k-super-secret-token")
    diag.register_section("leaky", lambda: ["Bearer t0k-super-secret-token"])
    text = json.dumps(diag.build_dump())
    assert "t0k-super-secret-token" not in text


@pytest.mark.parametrize("uri, secrets", [
    ("s3://bkt/team?endpoint_url=http://minio:minio-pass@minio:9000", ["minio-pass"]),
    ("s3://bkt/team?endpoint_url=http://minio:9000&token=abcSECRET", ["abcSECRET"]),
    ("postgresql://vmn:pg-pass@db:5432/vmn?sslpassword=sslSECRET", ["pg-pass", "sslSECRET"]),
    ("host=db user=vmn password=kvSECRET", ["kvSECRET"]),
])
def test_redact_uri_strips_credentials_and_query_secrets(uri, secrets):
    redacted = redact_uri(uri)
    for secret in secrets:
        assert secret not in redacted
    assert ("bkt" in redacted) or ("db" in redacted)


def test_redact_uri_keeps_the_endpoint_host():
    redacted = redact_uri("s3://bkt/team?endpoint_url=http://u:p@minio:9000")
    assert "minio:9000" in redacted and "s3://bkt/team" in redacted


def test_process_section_carries_redacted_server_options():
    diag.record_server_options({
        "host": "0.0.0.0", "port": 8265, "read_only": True,
        "store": "s3://bkt/p?endpoint_url=http://ak:sk-SECRET@minio:9000",
        "db": "postgresql://u:db-SECRET@h/d", "token": "tok-SECRET",
    })
    section = diag.process_section()
    text = json.dumps(section)
    for secret in ("sk-SECRET", "db-SECRET", "tok-SECRET"):
        assert secret not in text
    options = section["server_options"]
    assert options["host"] == "0.0.0.0" and options["read_only"] is True
    assert options["token"] == "set"
    assert {"python", "rss_bytes", "threads", "gc_counts", "uptime_sec"} <= set(section)
