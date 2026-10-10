"""Read a unified diff (``git diff``) or a ``git format-patch --stdout`` mbox.

``parse_patch(text, prefix="")`` -> ``{"files", "symbols", "commits", "authors"}``,
in order of appearance with repeats kept (core/features.py dedupes and caps):
the paths of every ``diff --git`` section (renames: new then old path), one
``path::name`` per hunk context, each message's ``Subject:`` without git's
``[PATCH n/m]`` and its ``From:`` as ``{"name", "email"}``. Headers are read only
after an mbox ``From <sha> <date>`` line and until the blank line ending them;
diff content lines always carry a ``+``/``-``/`` `` prefix, so they never look
like headers, sections or hunks.
"""
from __future__ import annotations

import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from vmn_exp.core.features_symbols import hunk_symbol

_MBOX_FROM = re.compile(r"From (?:[0-9a-f]{40}|[0-9a-f]{64})(?: |$)")
_HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(.*)")
_SUBJECT_PREFIX = re.compile(r"^\[[^\]]*\]\s*")
_RENAME = re.compile(r"(rename|copy) (from|to) (.+)")
_DIFF_GIT = "diff --git "
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def parse_patch(text: str, prefix: str = "") -> dict:
    parser = _Parser(prefix)
    for line in text.splitlines():
        parser.feed(line)
    parser.close()
    return parser.out


class _Parser:
    def __init__(self, prefix):
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.out = {"files": [], "symbols": [], "commits": [], "authors": []}
        self.state = "start"
        self.headers = []
        self.section = None
        self.path = None

    def feed(self, line):
        if _MBOX_FROM.match(line):
            self.close()
            self.state, self.headers = "headers", []
        elif self.state == "headers":
            self._header_line(line)
        elif line.startswith(_DIFF_GIT):
            self._end_header()
            self.section = _section(line[len(_DIFF_GIT):])
            self.state = "section"
        elif self.state == "section":
            self._section_line(line)
        elif self.state == "hunks":
            self._hunk(_HUNK.match(line))

    def close(self):
        if self.state == "headers":
            self._read_headers()
        self._end_header()
        self.state = "start"

    def _header_line(self, line):
        if not line:
            self._read_headers()
            self.state = "body"
        elif line[:1] in " \t" and self.headers:
            self.headers[-1] += " " + line.strip()
        else:
            self.headers.append(line)

    def _read_headers(self):
        fields = {}
        for header in self.headers:
            name, _, value = header.partition(":")
            fields.setdefault(name.strip().lower(), value.strip())
        subject = " ".join(_decoded(fields.get("subject", "")).split())
        subject = _SUBJECT_PREFIX.sub("", subject, count=1)
        if subject:
            self.out["commits"].append(subject)
        name, email = parseaddr(fields.get("from", ""))
        if name or email:
            self.out["authors"].append({"name": _decoded(name), "email": email})
        self.headers = []

    def _section_line(self, line):
        renamed, hunk = _RENAME.match(line), _HUNK.match(line)
        if renamed:
            kind, side, path = renamed.groups()
            self.section["old" if side == "from" else "new"] = _unquote(path)
            self.section["copy"] = kind == "copy"
        elif line.startswith("deleted file mode"):
            self.section["deleted"] = True
        elif line.startswith("GIT binary patch") or line.startswith("Binary files "):
            self._end_header()
            self.state = "binary"
        elif hunk:
            self._end_header()
            self.state = "hunks"
            self._hunk(hunk)

    def _hunk(self, match):
        name = hunk_symbol(match.group(1)) if match else None
        if name:
            self.out["symbols"].append(f"{self.path}::{name}")

    def _end_header(self):
        """The section's paths are known once its extended header lines are read."""
        section, self.section = self.section, None
        if section is None:
            return
        old, new = self.prefix + section["old"], self.prefix + section["new"]
        self.path = old if section["deleted"] else new
        changed = [self.path] if section["copy"] or old == new else [new, old]
        self.out["files"].extend(changed)


def _section(rest: str) -> dict:
    old, new = _strip_prefixes(*_header_paths(rest))
    return {"old": old, "new": new, "deleted": False, "copy": False}


def _header_paths(rest: str):
    """The two paths of ``diff --git <a> <b>``; unquoted paths may hold spaces, so
    split in the middle when both halves name the same file (renames are fixed
    by their ``rename from/to`` lines)."""
    if rest.startswith('"'):
        end = _closing_quote(rest)
        return _unquote(rest[: end + 1]), _unquote(rest[end + 2:])
    if rest.endswith('"') and ' "' in rest:
        cut = rest.rfind(' "')
        return rest[:cut], _unquote(rest[cut + 1:])
    cut = len(rest) // 2
    if rest[cut:cut + 1] == " " and _same_file(rest[:cut], rest[cut + 1:]):
        return rest[:cut], rest[cut + 1:]
    old, sep, new = rest.partition(" b/")
    return (old, "b/" + new) if sep else (rest, rest)


def _same_file(a: str, b: str) -> bool:
    return a == b or (a[1:2] == b[1:2] == "/" and a[2:] == b[2:])


def _strip_prefixes(a: str, b: str):
    """Without git's ``a/`` ``b/`` (or mnemonic ``c/`` ``w/`` ...) prefixes; a
    ``diff.noprefix`` header names the same path twice."""
    if a != b and a[1:2] == b[1:2] == "/":
        return a[2:], b[2:]
    return a, b


def _closing_quote(text: str) -> int:
    index = 1
    while index < len(text) and text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    return index


def _unquote(text: str) -> str:
    """Undo git's C-style quoting of a path (``core.quotePath``: octal UTF-8 bytes)."""
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        return text
    body, out, index = text[1:-1], bytearray(), 0
    while index < len(body):
        char = body[index]
        if char == "\\" and body[index + 1: index + 4].isdigit():
            out.append(int(body[index + 1: index + 4], 8) & 0xFF)
            index += 4
        elif char == "\\" and body[index + 1: index + 2] in _ESCAPES:
            out.append(_ESCAPES[body[index + 1]])
            index += 2
        else:
            out += char.encode("utf-8")
            index += 1
    return out.decode("utf-8", "replace")


def _decoded(value: str) -> str:
    """An RFC 2047 header value (``=?UTF-8?q?...?=``) as text."""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value
