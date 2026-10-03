"""BYO-bucket onboarding snippets (plan 11 §6.3)."""
import json

from vmn_exp.ui import onboarding

BUCKET, PREFIX, ACCOUNT, EXT = "cust-bucket", "exps", "111122223333", "ext-123"


def _actions(policy):
    return [a for s in policy["Statement"] for a in s["Action"]]


def _resources(policy, action):
    return [r for s in policy["Statement"] if action in s["Action"] for r in s["Resource"]]


def test_read_only_set_grants_get_and_list_on_the_prefix():
    policy = onboarding.permission_policy(BUCKET, PREFIX, edits=False)
    assert sorted(set(_actions(policy))) == ["s3:GetObject", "s3:ListBucket"]
    assert _resources(policy, "s3:GetObject") == [f"arn:aws:s3:::{BUCKET}/{PREFIX}/*"]
    listing = [s for s in policy["Statement"] if "s3:ListBucket" in s["Action"]][0]
    assert listing["Condition"]["StringLike"]["s3:prefix"] == [f"{PREFIX}/*"]


def test_edit_set_puts_only_the_server_edit_paths():
    policy = onboarding.permission_policy(BUCKET, PREFIX, edits=True, writer_id="srv")
    base = f"arn:aws:s3:::{BUCKET}/{PREFIX}"
    assert sorted(_resources(policy, "s3:PutObject")) == sorted([
        f"{base}/runs/*/*/metadata.yml",
        f"{base}/registry/*",
        f"{base}/reports/*",
        f"{base}/comments/*",
        f"{base}/runs/*/*/log/srv*",
        f"{base}/journal/*",
        f"{base}/server/*",
    ])


def test_no_permission_set_ever_deletes():
    for edits in (False, True):
        policy = onboarding.permission_policy(BUCKET, PREFIX, edits=edits)
        assert not [a for a in _actions(policy) if "Delete" in a]


def test_trust_policy_requires_the_org_external_id():
    trust = onboarding.trust_policy(ACCOUNT, EXT)
    (stmt,) = trust["Statement"]
    assert stmt["Principal"] == {"AWS": f"arn:aws:iam::{ACCOUNT}:root"}
    assert stmt["Condition"] == {"StringEquals": {"sts:ExternalId": EXT}}


def test_lifecycle_rule_expires_the_journal_after_two_days():
    rule = onboarding.lifecycle_rule(PREFIX)
    assert rule["Filter"] == {"Prefix": f"{PREFIX}/journal/"}
    assert rule["Expiration"] == {"Days": 2}
    assert rule["Status"] == "Enabled"


def test_cors_allows_signed_get_from_the_server_origin():
    (rule,) = onboarding.cors_rules(["https://vmn.example"])
    assert rule["AllowedMethods"] == ["GET"]
    assert rule["AllowedOrigins"] == ["https://vmn.example"]


def test_cloudformation_snippet_carries_role_policy_lifecycle_and_cors():
    text = onboarding.cloudformation(BUCKET, PREFIX, ACCOUNT, EXT, edits=True,
                                     origins=["https://vmn.example"])
    doc = json.loads(text)
    kinds = sorted(r["Type"] for r in doc["Resources"].values())
    assert kinds == ["AWS::IAM::Role"]
    role = doc["Resources"]["VmnExpReader"]["Properties"]
    assert role["RoleName"] == "vmn-exp-reader"
    assert EXT in text and "s3:PutObject" in text and "Delete" not in text


def test_bucket_settings_hold_the_lifecycle_and_cors_for_an_existing_bucket():
    settings = onboarding.bucket_settings(PREFIX, ["https://vmn.example"])
    assert settings["lifecycle"] == {"Rules": [onboarding.lifecycle_rule(PREFIX)]}
    assert settings["cors"] == {"CORSRules": onboarding.cors_rules(["https://vmn.example"])}


def test_terraform_snippet_names_the_external_id_and_journal_rule():
    text = onboarding.terraform(BUCKET, PREFIX, ACCOUNT, EXT, edits=False,
                                origins=["https://vmn.example"])
    assert 'resource "aws_iam_role" "vmn_exp_reader"' in text
    assert EXT in text
    assert f"{PREFIX}/journal/" in text
    assert "aws_s3_bucket_cors_configuration" in text
    assert "PutObject" not in text and "Delete" not in text
