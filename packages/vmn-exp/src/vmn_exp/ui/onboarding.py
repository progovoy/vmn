#!/usr/bin/env python3
"""BYO-bucket onboarding snippets (plan 11 §6.3), AWS first.

The customer creates role ``vmn-exp-reader`` trusting our account with
``ExternalId = <org external id>`` and one of two permission sets: read-only,
or read + the puts server-side edits need. Neither set ever deletes. The
bucket gets a lifecycle rule expiring ``<prefix>/journal/`` after 2 days and
CORS for signed browser downloads (:func:`bucket_settings`, applied with
``aws s3api put-bucket-lifecycle-configuration`` / ``put-bucket-cors``).
"""
import json

ROLE_NAME = "vmn-exp-reader"
SERVER_WRITER_ID = "vmn-server"
JOURNAL_DAYS = 2
# Record-relative paths server-side edits write (§7.1); "server/" holds the
# probe's conditional-write key. {w} is the server's writer id.
EDIT_PATHS = (
    "runs/*/*/metadata.yml", "registry/*", "reports/*", "comments/*",
    "runs/*/*/log/{w}*", "journal/*", "server/*",
)


def _statement(actions, resources, condition=None):
    stmt = {"Effect": "Allow", "Action": list(actions), "Resource": list(resources)}
    if condition:
        stmt["Condition"] = condition
    return stmt


def permission_policy(bucket, prefix, edits=False, writer_id=SERVER_WRITER_ID):
    base = f"arn:aws:s3:::{bucket}/{prefix}"
    statements = [
        _statement(["s3:ListBucket"], [f"arn:aws:s3:::{bucket}"],
                   {"StringLike": {"s3:prefix": [f"{prefix}/*"]}}),
        _statement(["s3:GetObject"], [f"{base}/*"]),
    ]
    if edits:
        paths = [f"{base}/{p.format(w=writer_id)}" for p in EDIT_PATHS]
        statements.append(_statement(["s3:PutObject"], paths))
    return {"Version": "2012-10-17", "Statement": statements}


def trust_policy(account_id, external_id):
    return {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
        "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
    }]}


def lifecycle_rule(prefix):
    return {
        "ID": "vmn-journal-expiry",
        "Filter": {"Prefix": f"{prefix}/journal/"},
        "Status": "Enabled",
        "Expiration": {"Days": JOURNAL_DAYS},
    }


def cors_rules(origins):
    return [{
        "AllowedMethods": ["GET"],
        "AllowedOrigins": list(origins),
        "AllowedHeaders": ["*"],
        "MaxAgeSeconds": 300,
    }]


def bucket_settings(prefix, origins):
    return {
        "lifecycle": {"Rules": [lifecycle_rule(prefix)]},
        "cors": {"CORSRules": cors_rules(origins)},
    }


def cloudformation(bucket, prefix, account_id, external_id, edits=False, origins=()):
    """A CloudFormation template (JSON) creating the role. *origins* is
    accepted for symmetry with :func:`terraform`; CORS and the lifecycle rule
    of an existing bucket are in :func:`bucket_settings`."""
    role = {
        "Type": "AWS::IAM::Role",
        "Properties": {
            "RoleName": ROLE_NAME,
            "AssumeRolePolicyDocument": trust_policy(account_id, external_id),
            "Policies": [{
                "PolicyName": "vmn-exp-access",
                "PolicyDocument": permission_policy(bucket, prefix, edits),
            }],
        },
    }
    template = {"AWSTemplateFormatVersion": "2010-09-09", "Resources": {"VmnExpReader": role}}
    return json.dumps(template, indent=2)


def _hcl_json(doc):
    return "jsonencode(" + json.dumps(doc, indent=2) + ")"


def terraform(bucket, prefix, account_id, external_id, edits=False, origins=()):
    """Terraform for the role, its policy, the journal lifecycle rule and CORS."""
    rule = lifecycle_rule(prefix)
    return f'''resource "aws_iam_role" "vmn_exp_reader" {{
  name               = "{ROLE_NAME}"
  assume_role_policy = {_hcl_json(trust_policy(account_id, external_id))}
}}

resource "aws_iam_role_policy" "vmn_exp_access" {{
  role   = aws_iam_role.vmn_exp_reader.id
  policy = {_hcl_json(permission_policy(bucket, prefix, edits))}
}}

resource "aws_s3_bucket_lifecycle_configuration" "vmn_journal" {{
  bucket = "{bucket}"
  rule {{
    id     = "{rule["ID"]}"
    status = "Enabled"
    filter {{
      prefix = "{prefix}/journal/"
    }}
    expiration {{
      days = {JOURNAL_DAYS}
    }}
  }}
}}

resource "aws_s3_bucket_cors_configuration" "vmn_signed_downloads" {{
  bucket = "{bucket}"
  cors_rule {{
    allowed_methods = ["GET"]
    allowed_origins = {json.dumps(list(origins))}
    allowed_headers = ["*"]
    max_age_seconds = 300
  }}
}}
'''
