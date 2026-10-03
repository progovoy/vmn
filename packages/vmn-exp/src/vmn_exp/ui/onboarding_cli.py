#!/usr/bin/env python3
"""``vmn-exp ui onboarding --store s3://bucket/prefix [--edits] [--format
json|cloudformation|terraform] [--account-id --external-id] [--origin ...]``
(plan 11 §6.3): print what a customer applies to let the server read (and,
with ``--edits``, edit) their bucket.

``json`` prints the permission policy and bucket settings (lifecycle + CORS),
plus the trust policy when the account and external id are given; the
templates need both.
"""
import json

from version_stamp.api import VMN_LOGGER
from vmn_exp.ui import onboarding

_TEMPLATES = {"cloudformation": onboarding.cloudformation, "terraform": onboarding.terraform}


def _bucket_prefix(uri):
    from vmn_exp.storage.uri import parse_store_uri

    if not uri:
        return None
    try:
        parsed = parse_store_uri(uri)
    except ValueError:
        return None
    return (parsed.location, parsed.path) if parsed.scheme == "s3" else None


def _json_doc(bucket, prefix, args, origins):
    doc = {
        "permission_policy": onboarding.permission_policy(bucket, prefix, args.edits),
        "bucket_settings": onboarding.bucket_settings(prefix, origins),
    }
    if args.account_id and args.external_id:
        doc["trust_policy"] = onboarding.trust_policy(args.account_id, args.external_id)
    return json.dumps(doc, indent=2)


def handle_onboarding(args):
    target = _bucket_prefix(getattr(args, "store", None))
    if target is None:
        VMN_LOGGER.error("onboarding needs --store s3://<bucket>/<prefix>")
        return 1
    bucket, prefix = target
    origins = args.origin or []
    fmt = args.onboarding_format
    if fmt == "json":
        print(_json_doc(bucket, prefix, args, origins))
        return 0
    if not (args.account_id and args.external_id):
        VMN_LOGGER.error(f"--format {fmt} needs --account-id and --external-id")
        return 1
    print(_TEMPLATES[fmt](bucket, prefix, args.account_id, args.external_id,
                          edits=args.edits, origins=origins))
    return 0
