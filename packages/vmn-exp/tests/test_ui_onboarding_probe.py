"""The BYO-bucket onboarding probe (plan 11 §6.3): STS + S3 via moto."""
import boto3
import pytest
from botocore.exceptions import ClientError

from s3_helpers import BUCKET, PREFIX, mocked_bucket
from vmn_exp.ui import onboarding
from vmn_exp.ui.onboarding_probe import probe_role

ROLE = "arn:aws:iam::123456789012:role/vmn-exp-reader"
EXT = "ext-123"


def _denied(op):
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


class _Client:
    """An S3 client refusing the operations named in *deny*."""

    def __init__(self, inner, deny=()):
        self._inner, self._deny = inner, set(deny)

    def __getattr__(self, name):
        if name in self._deny:
            def refuse(**kwargs):
                raise _denied(name)
            return refuse
        return getattr(self._inner, name)


def _factory(deny=()):
    return lambda creds: _Client(boto3.client("s3", **creds), deny)


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        s3 = boto3.client("s3")
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/runs/app/1/metadata.yml", Body=b"a: 1")
        yield s3


def _lifecycle(s3):
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET,
        LifecycleConfiguration={"Rules": [onboarding.lifecycle_rule(PREFIX)]},
    )


def _failed(probe):
    return [c.name for c in probe.checks if not c.ok]


def test_read_edit_role_without_delete_passes(bucket):
    _lifecycle(bucket)
    probe = probe_role(ROLE, EXT, BUCKET, PREFIX, edits=True,
                       client_for=_factory(deny={"delete_object"}))
    assert _failed(probe) == []
    assert probe.capabilities == ["read", "edit"]
    assert not probe.refused and probe.warnings == []


def test_read_only_role_is_detected(bucket):
    _lifecycle(bucket)
    probe = probe_role(ROLE, EXT, BUCKET, PREFIX, edits=True,
                       client_for=_factory(deny={"put_object", "delete_object"}))
    assert _failed(probe) == ["write"]
    assert probe.capabilities == ["read"]
    assert not probe.refused


def test_role_that_can_delete_is_refused(bucket):
    _lifecycle(bucket)
    probe = probe_role(ROLE, EXT, BUCKET, PREFIX, edits=True, client_for=_factory())
    assert "no_delete" in _failed(probe)
    assert probe.refused and probe.capabilities == []


def test_each_failing_check_is_reported(bucket):
    probe = probe_role(ROLE, EXT, BUCKET, PREFIX, edits=False,
                       client_for=_factory(deny={"list_objects_v2", "get_object",
                                                 "delete_object"}))
    assert _failed(probe) == ["list", "read"]
    assert probe.capabilities == []


def test_missing_lifecycle_rule_warns(bucket):
    probe = probe_role(ROLE, EXT, BUCKET, PREFIX, client_for=_factory(deny={"delete_object"}))
    assert any("lifecycle" in w for w in probe.warnings)
    assert probe.capabilities == ["read"]


class _Sts:
    def __init__(self, expected):
        self.expected, self.calls = expected, []

    def assume_role(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("ExternalId") != self.expected:
            raise _denied("AssumeRole")
        return boto3.client("sts").assume_role(**kwargs)


def test_probe_assumes_the_role_with_the_org_external_id(bucket):
    sts = _Sts(EXT)
    probe_role(ROLE, EXT, BUCKET, PREFIX, sts=sts, client_for=_factory(deny={"delete_object"}))
    assert sts.calls[0]["RoleArn"] == ROLE and sts.calls[0]["ExternalId"] == EXT


def test_wrong_external_id_fails_assume_role_and_stops(bucket):
    probe = probe_role(ROLE, "wrong", BUCKET, PREFIX, sts=_Sts(EXT), client_for=_factory())
    assert [(c.name, c.ok) for c in probe.checks] == [("assume_role", False)]
    assert probe.capabilities == []
