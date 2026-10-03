#!/usr/bin/env python3
"""Validate a customer's onboarding role (plan 11 §6.3).

Checks, in order, each reported: ``assume_role`` (with the org ExternalId),
``list`` and ``read`` (one object under the prefix), ``write`` (read + edits
only: a conditional put of a probe key under ``<prefix>/server/``), and
``no_delete`` (a delete must answer ``AccessDenied``; a role that can delete is
refused outright). A missing journal lifecycle rule is a warning.
"""
import uuid
from dataclasses import dataclass, field
from typing import List

from vmn_exp.ui.storage_access import EDIT, READ, SERVER_AREA

SESSION_NAME = "vmn-exp-onboarding"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class RoleProbe:
    checks: List[Check] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    refused: bool = False

    def passed(self, name):
        return any(c.name == name and c.ok for c in self.checks)


def _code(exc):
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _try(probe, name, action):
    try:
        detail = action() or ""
    except Exception as e:
        probe.checks.append(Check(name, False, str(e)))
        return False
    probe.checks.append(Check(name, True, detail))
    return True


def _assume(sts, role_arn, external_id):
    resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=SESSION_NAME,
                           ExternalId=external_id, DurationSeconds=900)
    c = resp["Credentials"]
    return {"aws_access_key_id": c["AccessKeyId"], "aws_secret_access_key": c["SecretAccessKey"],
            "aws_session_token": c["SessionToken"]}


def _read_one(s3, bucket, prefix):
    listed = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/runs/", MaxKeys=1)
    objects = listed.get("Contents") or []
    if not objects:
        return "no records yet"
    s3.get_object(Bucket=bucket, Key=objects[0]["Key"])["Body"].read()
    return objects[0]["Key"]


def _probe_key(prefix):
    return f"{prefix}/{SERVER_AREA}/probe-{uuid.uuid4().hex}"


def _write(s3, bucket, prefix):
    s3.put_object(Bucket=bucket, Key=_probe_key(prefix), Body=b"probe", IfNoneMatch="*")


def _cannot_delete(s3, bucket, prefix):
    try:
        s3.delete_object(Bucket=bucket, Key=_probe_key(prefix))
    except Exception as e:
        if _code(e) == "AccessDenied":
            return "delete refused"
        raise
    raise PermissionError("the role can delete objects; remove every Delete* permission")


def _has_journal_rule(s3, bucket, prefix):
    try:
        rules = s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except Exception:
        return False
    want = f"{prefix}/journal/"
    return any(
        r.get("Status") == "Enabled"
        and (r.get("Filter", {}).get("Prefix") or r.get("Prefix")) == want
        and r.get("Expiration")
        for r in rules
    )


def _default_client(creds):
    import boto3

    return boto3.client("s3", **creds)


def probe_role(role_arn, external_id, bucket, prefix, edits=False, sts=None,
               client_for=_default_client):
    """Run every onboarding check of *role_arn* on ``s3://bucket/prefix``."""
    if sts is None:
        import boto3

        sts = boto3.client("sts")
    probe = RoleProbe()
    creds = {}

    def assume():
        creds.update(_assume(sts, role_arn, external_id))

    if not _try(probe, "assume_role", assume):
        return probe
    s3 = client_for(creds)
    readable = _try(probe, "list", lambda: s3.list_objects_v2(
        Bucket=bucket, Prefix=f"{prefix}/", MaxKeys=1) and None)
    readable = _try(probe, "read", lambda: _read_one(s3, bucket, prefix)) and readable
    writable = edits and _try(probe, "write", lambda: _write(s3, bucket, prefix))
    if not _try(probe, "no_delete", lambda: _cannot_delete(s3, bucket, prefix)):
        probe.refused = True
        return probe
    if not _has_journal_rule(s3, bucket, prefix):
        probe.warnings.append(f"no lifecycle rule expiring {prefix}/journal/ after "
                              "2 days; the journal will grow without bound")
    if readable:
        probe.capabilities = [READ, EDIT] if writable else [READ]
    return probe
