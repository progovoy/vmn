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
