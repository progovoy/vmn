#!/usr/bin/env python3
"""The SSRF / abuse guard on store workspace URIs (plan 11 §6.3).

In ``tenancy: multi`` only ``s3://``, ``gs://`` and ``az://`` stores may be
connected, and an ``endpoint_url`` only when the server config allowlists it
(``server.endpoint_allowlist``); ``file://`` and plugin schemes are refused.
Single tenancy accepts any registered scheme, as before.
"""
from vmn_exp.storage.uri import parse_store_uri

MULTI_TENANT_SCHEMES = ("s3", "gs", "az")
ENDPOINT_OPTION = "endpoint_url"


def check_workspace_uri(uri, tenancy="single", endpoint_allowlist=()):
    """The reason *uri* may not be connected, or None."""
    if tenancy != "multi":
        return None
    try:
        parsed = parse_store_uri(uri)
    except ValueError as e:
        return str(e)
    if parsed.scheme not in MULTI_TENANT_SCHEMES:
        return f"Only {', '.join(s + '://' for s in MULTI_TENANT_SCHEMES)} stores are allowed"
    unknown = sorted(set(parsed.options) - {ENDPOINT_OPTION})
    if unknown:
        return f"Store URI option(s) not allowed: {', '.join(unknown)}"
    endpoint = parsed.options.get(ENDPOINT_OPTION)
    if endpoint and endpoint.rstrip("/") not in {e.rstrip("/") for e in endpoint_allowlist}:
        return f"endpoint_url {endpoint} is not in the server's endpoint allowlist"
    return None
