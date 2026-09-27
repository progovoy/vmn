#!/usr/bin/env python3
"""Parse ``--input [name=]uri[#digest]`` CLI arguments.

A single small helper so the parsing logic is testable independently of argparse.
"""
import re

# A valid name token: starts with letter or underscore, followed by
# letters, digits, underscores, or hyphens.
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_\-]*$')


def parse_input_arg(s):
    """Parse an ``--input`` argument into ``(name, uri, digest)``.

    Format: ``[name=]uri[#digest]``

    *name* is extracted only when the token before the first ``=`` is an
    identifier-like string (alphanumeric/underscore/dash, starting with alpha
    or underscore) **and** no ``://`` appears before that ``=``.  This prevents
    a URI such as ``s3://bucket/path?key=value`` from being mis-read as
    ``name="s3://bucket/path?key"``.

    The *last* ``#`` in the URI portion splits off a digest, so
    ``s3://bucket/data#sha256:abc`` yields digest ``"sha256:abc"``.

    Returns ``(name, uri, digest)`` where *name* and *digest* may be ``None``.
    """
    name = None
    eq_idx = s.find("=")
    if eq_idx != -1:
        scheme_idx = s.find("://")
        # name= only when :// doesn't appear before the first =
        before_eq = s[:eq_idx]
        no_scheme_before_eq = scheme_idx == -1 or scheme_idx >= eq_idx
        if no_scheme_before_eq and _IDENT_RE.match(before_eq):
            name = before_eq
            s = s[eq_idx + 1:]

    # Last '#' splits digest
    hash_idx = s.rfind("#")
    if hash_idx != -1:
        uri = s[:hash_idx]
        digest = s[hash_idx + 1:] or None
    else:
        uri = s
        digest = None

    return name, uri, digest
