"""Read a unified diff (``git diff``) or a ``git format-patch --stdout`` mbox.

``parse_patch(text, prefix="", skip_authors=())`` -> ``{"files", "symbols",
"commits", "authors"}``, in order of appearance with repeats kept
(core/features.py dedupes and caps): the paths of every ``diff --git`` section
(renames: new then old path), a ``path::name`` per function a change is in and
per definition an added or removed line makes
(:func:`~vmn_exp.core.features_symbols.defined_symbol`), each message's
``Subject:`` without git's ``[PATCH n/m]`` and its ``From:`` as ``{"name",
"email"}``. A change's function is its hunk's
:class:`~vmn_exp.core.features_scope.HunkScope`; a line past a hunk's ``@@``
counts (format-patch's ``-- `` signature) changes nothing. Headers are read only
after an mbox ``From <sha> <date>`` line and until the blank line ending them;
a cover letter (``[PATCH 0/n]``) is skipped whole, as is a commit whose ``From:``
name is one of *skip_authors*. A ``diff --git`` line in a
commit message (before its ``---`` separator) opens no section unless it
follows a blank line and an extended header line follows it (a ``--no-stat``
mbox has no separator); such a section, a diff pasted into the message, is
forgotten at the separator: a ``---`` line outside a hunk (by its ``@@``
counts), or inside one that lacks only blank context lines git's message
cleanup drops (as many old as new lines left) when a diffstat or blank
(``--notes``) line follows; any other ``---`` is a removed ``--`` line. Lines
end at ``\n`` only; diff content lines always carry a ``+``/``-``/`` `` prefix,
so they never look like headers, sections or hunks.
"""
from __future__ import annotations

import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from vmn_exp.core.features_scope import HunkScope
from vmn_exp.core.features_symbols import defined_symbol

_MBOX_FROM = re.compile(r"From (?:[0-9a-f]{40}|[0-9a-f]{64})(?: |$)")
_HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(.*)")
_HUNK_LINE = ("+", "-", " ", "\\", "")  # "": a context line a message cleanup stripped
_SUBJECT_PREFIX = re.compile(r"^\[[^\]]*\]\s*")
_COVER_LETTER = re.compile(r"^\[[^\]]*\b0+/\d+\]")
_DIFFSTAT = re.compile(r" \S.* \| +(?:\d|Bin )")  # a diffstat line
_EXTENDED_HEADERS = ("index ", "old mode ", "new mode ", "deleted file mode ", "new file mode ",
                     "similarity index ", "dissimilarity index ", "rename from ", "copy from ",
                     "Binary files ", "--- ")
_RENAME = re.compile(r"(rename|copy) (from|to) (.+)")
_DIFF_GIT = "diff --git "
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def parse_patch(text: str, prefix: str = "", skip_authors=()) -> dict:
    parser = _Parser(prefix, frozenset(skip_authors))
    # Not splitlines(): it also splits on \f, \x1c-\x1e, \x85, U+2028/9 within a line.
    for line in text.split("\n"):
        parser.feed(line[:-1] if line.endswith("\r") else line)
    parser.close()
    return parser.out


class _Parser:
    def __init__(self, prefix, skip_authors):
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.skip_authors = skip_authors
        self.out = {"files": [], "symbols": [], "commits": [], "authors": []}
        self.state = "start"
        self.headers = []
        self.section = None
        self.path = None
        self.quoted = None  # a message's `diff --git` line, until the next line confirms it
        self.after_blank = False
        self.pasted = None  # (files, symbols) counts before a diff pasted in a message
        self.dashes = False  # a pasted hunk's `---` line, until the next line tells what it is
        self.old_left = self.new_left = 0  # the current hunk's lines still to come
        self.scope = HunkScope()

    def feed(self, line):
        if self.dashes:
            self._after_dashes(line)
        if _MBOX_FROM.match(line):
            self.close()
            self.state, self.headers = "headers", []
        elif self.state == "headers":
            self._header_line(line)
        elif self.state == "message":
            self._message_line(line)
        elif self.state == "cover":
            pass
        elif line.startswith(_DIFF_GIT):
            self._open_section(line)
        elif line == "---" and self.pasted:
            self._pasted_dashes()
        elif self.state == "section":
            self._section_line(line)
        elif self.state == "hunks":
            self._hunk_line(line)

    def _open_section(self, line):
        self._end_header()
        self.section = _section(line[len(_DIFF_GIT):])
        self.state = "section"
        self.old_left = self.new_left = 0

    def _pasted_dashes(self):
        """A ``---`` line after a pasted diff: the separator, a removed ``--``
        line, or (cleanup-shortened hunk) whichever the next line tells."""
        if self.old_left <= 0:
            self._forget_pasted()
        elif self.old_left == self.new_left:
            self.dashes = True
        else:
            self._hunk_line("---")

    def _after_dashes(self, line):
        self.dashes = False
        if not line or _DIFFSTAT.match(line):
            self._forget_pasted()
        else:
            self._hunk_line("---")

    def _forget_pasted(self):
        """The message's separator ends a diff pasted into it: none of it changed."""
        files, symbols = self.pasted
        del self.out["files"][files:], self.out["symbols"][symbols:]
        self.section, self.pasted, self.state = None, None, "body"

    def _message_line(self, line):
        """A commit message's line: it ends at ``---``, or at a ``diff --git``
        line confirmed as a section by the line after it."""
        quoted, self.quoted = self.quoted, None
        if line == "---":
            self.state = "body"
        elif quoted and line.startswith(_EXTENDED_HEADERS):
            self.pasted = (len(self.out["files"]), len(self.out["symbols"]))
            self._open_section(quoted)
            self._section_line(line)
        elif line.startswith(_DIFF_GIT) and self.after_blank:
            self.quoted = line
        self.after_blank = not line

    def close(self):
        if self.state == "headers":
            self._read_headers()
        self._end_header()
        self.state, self.quoted, self.pasted, self.dashes = "start", None, None, False

    def _header_line(self, line):
        if not line:
            self.state = "message" if self._read_headers() else "cover"
            self.after_blank = True
        elif line[:1] in " \t" and self.headers:
            self.headers[-1] += " " + line.strip()
        else:
            self.headers.append(line)

    def _read_headers(self):
        """Record the message's subject and author; False for a cover letter
        or a commit of a skipped author."""
        fields = {}
        for header in self.headers:
            name, _, value = header.partition(":")
            fields.setdefault(name.strip().lower(), value.strip())
        self.headers = []
        subject = " ".join(_decoded(fields.get("subject", "")).split())
        name, email = parseaddr(fields.get("from", ""))
        name = _decoded(name)
        if _COVER_LETTER.match(subject) or name in self.skip_authors:
            return False
        subject = _SUBJECT_PREFIX.sub("", subject, count=1)
        if subject:
            self.out["commits"].append(subject)
        if name or email:
            self.out["authors"].append({"name": name, "email": email})
        return True

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

    def _hunk_line(self, line):
        kind = line[:1]
        past = self.old_left <= 0 and self.new_left <= 0  # e.g. format-patch's `-- ` signature
        if kind in _HUNK_LINE:
            self.old_left -= kind in ("-", " ", "")
            self.new_left -= kind in ("+", " ", "")
        else:
            self.old_left = self.new_left = 0
        if past and kind in ("+", "-", " "):
            return
        if kind in ("+", "-"):
            self._change_line(kind, line[1:])
        elif kind == " ":
            self.scope.context_line(line[1:])
        else:
            self._hunk(_HUNK.match(line))

    def _hunk(self, match):
        if match:
            old, new, context = match.groups()
            self.old_left, self.new_left = int(old or 1), int(new or 1)
            self.scope = HunkScope(context)

    def _change_line(self, kind, text):
        self._symbol(self.scope.change_line(kind, text))
        self._symbol(defined_symbol(text, self.path))

    def _symbol(self, name):
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
