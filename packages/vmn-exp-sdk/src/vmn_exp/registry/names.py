"""Model name, alias name, and ref parsing for the model registry.

Model name rules
----------------
* Non-empty.
* Characters: letters (a-z, A-Z), digits (0-9), underscore (_), dot (.).
* Must not start with a dot (.).
* Must not contain a hyphen (-).  Hyphens appear in storage keys when app
  names with slashes are normalised (``/`` → ``-``); allowing them in model
  names would make keys ambiguous.
* Must not end with ``.v`` followed only by ASCII digits.  Version records are
  stored as ``<model>.v<N>``; the ``.v<digits>`` suffix must be unambiguous so
  ``parse_version_record`` is well-defined.

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

# Reserved pseudo-app name for all registry records.
REGISTRY_APP = "vmn-registry"

# First char must be letter/digit/underscore — dot and hyphen excluded from the
# lead, which also rejects empty strings (requires at least one character).
_MODEL_CHARS_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.]*$')
_VERSION_SUFFIX_RE = re.compile(r'\.v\d+$')
_VERSION_RECORD_RE = re.compile(r'^(.+)\.v(\d+)$')
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


def version_record_name(model: str, n: int) -> str:
    """Return the storage record name for version *n* of *model*.

    Example::

        >>> version_record_name('resnet', 3)
        'resnet.v3'
    """
    return f"{model}.v{n}"


def parse_version_record(name: str) -> tuple[str, int] | None:
    """Parse *name* as a version record name and return *(model, n)*.

    Returns ``None`` if *name* does not match the ``<model>.v<N>`` pattern.
    """
    m = _VERSION_RECORD_RE.match(name)
    if m is None:
        return None
    return m.group(1), int(m.group(2))


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
# Kinds, registry URIs and the usage record
# ---------------------------------------------------------------------------

KINDS = ("model", "dataset")

REGISTRY_SCHEME = "vmn-registry://"
_REGISTRY_URI_RE = re.compile(r'^(.+)@([1-9]\d*)$')

# A model's usage log lives in the sibling record ``<model>-uses``; model
# names never contain ``-``, so it can never collide with a model.
_USES_SUFFIX = "-uses"


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


def uses_record_name(model: str) -> str:
    """Record name of *model*'s usage log."""
    return f"{model}{_USES_SUFFIX}"


def is_uses_record(name: str) -> bool:
    return name.endswith(_USES_SUFFIX)
