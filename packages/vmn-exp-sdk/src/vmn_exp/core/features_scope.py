"""The function a diff hunk's changes are in (core/features_patch.py reads it).

A change is in what git's default funcname (no ``diff=`` driver) names for it:
the nearest old-file line above it that starts with a letter, ``_`` or ``$`` --
a def or class, but also an ``if __name__`` block, a constant or prose; never a
method or a nested def -- read as git prints it (its first 80 bytes, up to its
first byte that is not UTF-8). That is the last such line the hunk shows before
the change (a context line, or a removed line once its change run ends), else
the hunk header's name, which is empty when the hunk starts at the top of the
file or only blank, indented or comment lines are above it; so a
3-line-context patch (capture, backfill) names what a ``-U0`` one
(``import-mlflow --repo``) does. With a ``diff=`` driver, ``-U0`` names what
that driver's funcname picks.
"""
from __future__ import annotations

import re

from vmn_exp.core.features_symbols import hunk_symbol

_FUNCNAME_BYTES = 80  # git's funcname buffer (xdiff/xemit.c)
_FUNCNAME_LINE = re.compile(r"[A-Za-z_$]")  # a line git's default funcname picks
_NOT_UTF8 = re.compile("[\ud800-\udfff\ufffd]")  # a decoded byte that is not UTF-8


class HunkScope:
    def __init__(self, header_context: str = ""):
        self.name, self.line, self.named = hunk_symbol(header_context), None, False
        self.after_run = None  # a removed funcname line: the next change run's scope

    def context_line(self, text: str):
        """A context line ends a change run and may itself be a funcname line."""
        self._move(self.after_run)
        self.after_run = None
        self._move(_funcname_line(text))

    def change_line(self, kind: str, text: str) -> str | None:
        """The scope's name when this ``+``/``-`` line is the first change in it."""
        first = None if self.named else self._name()
        self.named = True
        if kind == "-":
            self.after_run = _funcname_line(text) or self.after_run
        return first

    def _move(self, line):
        """The funcname *line* is the scope; it is read once a change needs its name."""
        if line:
            self.line, self.named = line, False

    def _name(self):
        if self.line:
            self.name, self.line = hunk_symbol(_git_funcname(self.line)), None
        return self.name


def _funcname_line(text):
    return text if _FUNCNAME_LINE.match(text) else None


def _git_funcname(line: str) -> str:
    """*line* as git prints it as a funcname: its first 80 bytes, up to its
    first byte that is not UTF-8 (diff.c ``sane_truncate_line``) -- here the
    first lone surrogate (``surrogateescape``) or U+FFFD (``replace``)."""
    valid = _NOT_UTF8.split(line, 1)[0]
    return valid.encode("utf-8")[:_FUNCNAME_BYTES].decode("utf-8", "ignore")
