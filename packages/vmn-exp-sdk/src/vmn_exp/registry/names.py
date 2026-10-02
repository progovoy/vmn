"""Model name, alias name, and ref parsing for the model registry.

Model name rules
----------------
* Non-empty.
* Characters: letters (a-z, A-Z), digits (0-9), underscore (_), dot (.).
* Must not start with a dot (.).
* Must not contain a hyphen (-).  Hyphens appear in storage keys when app
  names with slashes are normalised (``/`` → ``-``); allowing them in model
  names would make keys ambiguous.
* Must not end with ``.v`` followed only by ASCII digits (kept from the
  pre-area layout, so names stay valid in both).

Records live in the store's ``registry`` area, one scope per model:
``header`` (header + audit log), ``v<N>`` (versions) and ``uses`` (usage log).

Alias name rules
----------------
* Non-empty.
* Characters: letters, digits, underscore (_), hyphen (-), dot (.).
* Reserved: the string ``'latest'`` (resolves to the newest version) and any
  string composed entirely of ASCII digits (resolves to a specific version
  number).  Neither may be used as an alias name.
"""
from __future__ import annotations

import re

HEADER_RECORD = "header"
USES_RECORD = "uses"

# First char must be letter/digit/underscore — dot and hyphen excluded from the
# lead, which also rejects empty strings (requires at least one character).
_MODEL_CHARS_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.]*$')
_VERSION_SUFFIX_RE = re.compile(r'\.v\d+$')
_VERSION_RECORD_RE = re.compile(r'^v([1-9]\d*)$')
_ALIAS_CHARS_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')


def valid_model_name(name: str) -> bool:
    """Return True iff *name* is a valid model name."""
    if not _MODEL_CHARS_RE.match(name):
        return False
    if _VERSION_SUFFIX_RE.search(name):
        return False
    return True


def valid_alias_name(name: str) -> bool:
    """Return True iff *name* is a valid, non-reserved alias name."""
    if not name:
        return False
    if name == 'latest' or name.isdigit():
        return False
    if not _ALIAS_CHARS_RE.match(name):
        return False
    return True


def version_record_name(n: int) -> str:
    """Record name of version *n* within its model's scope (``v3``)."""
    return f"v{n}"


def parse_version_record(name: str) -> int | None:
    """The version number of a ``v<N>`` record name, else None."""
    m = _VERSION_RECORD_RE.match(name)
    return int(m.group(1)) if m else None


def parse_ref(ref: str) -> tuple[str, str, object]:
    """Parse a model reference into *(model, kind, value)*.

    Supported forms:

    =====================  ================  =========
    Input                  kind              value
    =====================  ================  =========
    ``model@alias``        ``'alias'``       alias str
    ``model@3``            ``'version'``     int
    ``model@latest``       ``'latest'``      None
    ``model``              ``'latest'``      None
    =====================  ================  =========
    """
    if '@' in ref:
        model, _, qualifier = ref.partition('@')
        if qualifier == 'latest':
            return model, 'latest', None
        if qualifier.isdigit():
            return model, 'version', int(qualifier)
        return model, 'alias', qualifier
    return ref, 'latest', None


# ---------------------------------------------------------------------------
# Kinds and registry URIs
# ---------------------------------------------------------------------------

KINDS = ("model", "dataset")

REGISTRY_SCHEME = "vmn-registry://"
_REGISTRY_URI_RE = re.compile(r'^(.+)@([1-9]\d*)$')


def registry_uri(name: str, n: int) -> str:
    """``vmn-registry://<name>@<N>`` — always pinned to a number, never an alias."""
    return f"{REGISTRY_SCHEME}{name}@{n}"


def parse_registry_uri(uri) -> tuple[str, int] | None:
    """``(name, n)`` of a ``vmn-registry://<name>@<N>`` URI, else None."""
    if not isinstance(uri, str) or not uri.startswith(REGISTRY_SCHEME):
        return None
    m = _REGISTRY_URI_RE.match(uri[len(REGISTRY_SCHEME):])
    if m is None or not valid_model_name(m.group(1)):
        return None
    return m.group(1), int(m.group(2))

