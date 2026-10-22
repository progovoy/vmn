#!/usr/bin/env python3
"""Store URIs and DSNs as a dump may show them: no userinfo, no query values
other than an ``endpoint_url``'s host (itself redacted the same way)."""
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from vmn_exp.ui.diag.registry import REDACTED

# libpq key=value DSNs: ``host=db password=...``.
_KV_SECRET = re.compile(r"\b(password|sslpassword|passfile|secret|token)\s*=\s*\S+", re.I)
_KEEP_QUERY = {"endpoint_url"}


def redact_uri(uri):
    """*uri* with credentials and secret query values replaced by ``***``."""
    if not uri:
        return uri
    if "://" not in uri:
        return _KV_SECRET.sub(lambda m: f"{m.group(1)}={REDACTED}", uri)
    parts = urlsplit(uri)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{REDACTED}@{netloc.rsplit('@', 1)[1]}"
    query = "&".join(f"{key}={_query_value(key, value)}"
                     for key, value in parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _query_value(key, value):
    if key in _KEEP_QUERY and "://" in value:
        return redact_uri(value)
    return REDACTED
