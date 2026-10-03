"""``vmn-exp ui onboarding --store <uri> [--edits] [--format ...]`` prints the
BYO-bucket IAM policy, trust policy and bucket settings (plan 11 §6.3)."""
import json

import pytest

from version_stamp.core.logging import init_stamp_logger
from vmn_exp.ui import onboarding
from vmn_exp.ui.cli import handle_ui


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _run(capsys, *argv):
    from version_stamp.cli.args import parse_user_commands

    rc = handle_ui(parse_user_commands(["ui", "onboarding", *argv]))
    return rc, capsys.readouterr().out


def test_json_prints_the_read_only_policy_and_bucket_settings(capsys):
    rc, out = _run(capsys, "--store", "s3://acme/vmn")
    assert rc == 0
    doc = json.loads(out)
    assert doc["permission_policy"] == onboarding.permission_policy("acme", "vmn")
    assert doc["bucket_settings"] == onboarding.bucket_settings("vmn", [])
    assert "trust_policy" not in doc


def test_edits_add_the_server_writer_puts(capsys):
    rc, out = _run(capsys, "--store", "s3://acme/vmn", "--edits", "--format", "json")
    assert rc == 0
    policy = json.loads(out)["permission_policy"]
    assert policy == onboarding.permission_policy("acme", "vmn", edits=True)
    assert "runs/*/*/log/vmn-server*" in json.dumps(policy)


def test_trust_policy_with_account_and_external_id(capsys):
    rc, out = _run(capsys, "--store", "s3://acme/vmn", "--account-id", "123",
                   "--external-id", "vmn-x", "--origin", "https://vmn.acme.com")
    assert rc == 0
    doc = json.loads(out)
    assert doc["trust_policy"] == onboarding.trust_policy("123", "vmn-x")
    assert doc["bucket_settings"] == onboarding.bucket_settings("vmn", ["https://vmn.acme.com"])


@pytest.mark.parametrize("fmt,fn", [("cloudformation", onboarding.cloudformation),
                                    ("terraform", onboarding.terraform)])
def test_templates(capsys, fmt, fn):
    rc, out = _run(capsys, "--store", "s3://acme/vmn", "--edits", "--format", fmt,
                   "--account-id", "123", "--external-id", "vmn-x")
    assert rc == 0
    assert out.strip() == fn("acme", "vmn", "123", "vmn-x", edits=True).strip()


def test_templates_need_account_and_external_id(capsys):
    rc, _ = _run(capsys, "--store", "s3://acme/vmn", "--format", "terraform")
    assert rc == 1


@pytest.mark.parametrize("argv", [[], ["--store", "gs://acme/vmn"], ["--store", "file:///tmp/x"]])
def test_needs_an_s3_store(capsys, argv):
    rc, _ = _run(capsys, *argv)
    assert rc == 1
