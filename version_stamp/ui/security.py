#!/usr/bin/env python3
"""Request hardening for vmn ui.

Three independent guards the server wires in:

* **Host allowlist** — without a token the API is open to anything that can
  reach the port, and a DNS-rebinding page reaches ``127.0.0.1`` under its own
  hostname. Unknown ``Host`` headers are refused. With a token set, a rebinding
  page has no credential to use, so Host is not checked (reverse proxies may
  rewrite it freely).
* **Same-origin mutations** — browsers send ``Origin`` (or at least
  ``Referer``) on a cross-site POST/DELETE; one naming a foreign site is
  refused. Mutating bodies must also be ``application/json``, which is what
  makes a cross-site write a preflighted request the server never approves.
* **Path params** — app names and verstrs from URLs reach the filesystem, so
  anything that could walk out of ``.vmn/`` is a 400.
"""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from version_stamp.core.version_math import tag_name_to_app_name

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
# Starlette's TestClient sends ``Host: testserver``. Allowing it is harmless:
# a rebinding attack arrives under the attacker's own domain, never this name.
TEST_CLIENT_HOST = "testserver"
# A wildcard bind says nothing about the name clients will use.
_WILDCARD_BINDS = ("0.0.0.0", "::", "")

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")
BODY_METHODS = ("POST", "PUT", "PATCH")

_FORBIDDEN_APP_SEGMENTS = ("", ".", "..", "branch_conf")


def _norm_host(host):
    return host.strip().strip("[]").lower()


def hostname_of(host_header):
    """``example.com:8265`` / ``[::1]:8265`` → ``example.com`` / ``::1``."""
    if not host_header:
        return ""
    return (urlsplit("//" + host_header.strip()).hostname or "").lower()


def is_json_content_type(value):
    media = (value or "").split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


def _sender_netloc(headers):
    """``host[:port]`` of the page that sent the request; None when no browser
    context is attached (curl, scripts, the SDK)."""
    origin = headers.get("origin")
    if origin:
        # "null" is a sandboxed iframe or a file:// page: never same-origin.
        return "null" if origin == "null" else urlsplit(origin).netloc.lower()
    referer = headers.get("referer")
    return urlsplit(referer).netloc.lower() if referer else None


@dataclass(frozen=True)
class RequestGuard:
    """Which Hosts the server answers and which origins may mutate.

    *hosts* gate the ``Host`` header when no token is required. *origins* are
    the extra hosts (``--allowed-host``) whose pages may send mutations even
    though they differ from ``Host`` — a reverse proxy that rewrites it.
    """

    hosts: frozenset
    origins: frozenset
    token_required: bool

    @classmethod
    def build(cls, bind_host=None, allowed_hosts=None, token_required=False):
        extra = {_norm_host(h) for h in allowed_hosts or () if h.strip()}
        hosts = set(LOOPBACK_HOSTS) | {TEST_CLIENT_HOST} | extra
        if bind_host and bind_host not in _WILDCARD_BINDS:
            hosts.add(_norm_host(bind_host))
        return cls(frozenset(hosts), frozenset(extra), token_required)

    def host_allowed(self, host_header):
        return "*" in self.hosts or hostname_of(host_header) in self.hosts

    def cross_site(self, headers):
        netloc = _sender_netloc(headers)
        if netloc is None or netloc == (headers.get("host") or "").lower():
            return False
        return "*" not in self.origins and hostname_of(netloc) not in self.origins

    def reject_reason(self, method, path, headers):
        """``(status, detail)`` when a request must be refused, else None."""
        if not path.startswith("/api"):
            return None
        if not self.token_required and not self.host_allowed(headers.get("host")):
            return 403, "Host not allowed"
        if method in MUTATING_METHODS and self.cross_site(headers):
            return 403, "Cross-site request refused"
        if method in BODY_METHODS and not is_json_content_type(
            headers.get("content-type")
        ):
            return 415, "Content-Type must be application/json"
        return None


# ---------------------------------------------------------------------------
# path params
# ---------------------------------------------------------------------------


def safe_app_name(app_tag):
    """Decode a dashed URL app tag, or None when it is not a vmn app name.

    Mirrors vmn's own rule (no leading ``/``, no ``branch_conf`` segment) and
    also refuses empty/``.``/``..`` segments and backslashes, which the
    ``-``→``/`` decoding would otherwise turn into a path walk.
    """
    if not app_tag or "\\" in app_tag or "\0" in app_tag:
        return None
    name = tag_name_to_app_name(app_tag)
    if name.startswith("/"):
        return None
    if any(seg in _FORBIDDEN_APP_SEGMENTS for seg in name.split("/")):
        return None
    return name


def safe_segment(value):
    """A verstr or artifact name that stays one path component."""
    if value is None:
        return True
    return not (
        value in ("", ".")
        or ".." in value
        or "/" in value
        or "\\" in value
        or "\0" in value
    )


def within(base, candidate):
    """Whether *candidate* resolves inside directory *base* (symlinks followed)."""
    base_real = os.path.realpath(base)
    cand_real = os.path.realpath(candidate)
    try:
        return os.path.commonpath([base_real, cand_real]) == base_real
    except ValueError:  # different drives on Windows
        return False
