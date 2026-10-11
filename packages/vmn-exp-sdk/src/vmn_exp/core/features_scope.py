"""The function a diff hunk's changes are in (core/features_patch.py reads it).

A change is in what git's default funcname (no ``diff=`` driver) names for it:
the nearest old-file line above it that starts with a letter, ``_`` or ``$`` --
a def or class, but also an ``if __name__`` block, a constant or prose; never a
method or a nested def -- cut at 80 characters (git keeps 80 bytes). That is the
hunk header's name, else the one a context line, or a removed line once its
change run ends, gives before the change in the hunk; so a 3-line-context patch
(capture, backfill) names what a ``-U0`` one (``import-mlflow --repo``) does.
With a ``diff=`` driver, ``-U0`` names what that driver's funcname picks.

A gap, for now: a hunk whose header names nothing (it starts at the top of the
file, or only blank, indented or comment lines are above it) takes no scope
from its lines, where ``-U0`` names, e.g., the file's first function.
"""
from __future__ import annotations

import re

from vmn_exp.core.features_symbols import FALLBACK_CHARS, hunk_symbol

_FUNCNAME_LINE = re.compile(r"[A-Za-z_$]")  # a line git's default funcname picks


class HunkScope:
    def __init__(self, header_context: str = ""):
        self.name, self.named = hunk_symbol(header_context), False
        self.after_run = None  # a removed funcname line: the next change run's scope

    def context_line(self, text: str):
        """A context line ends a change run and may itself be a funcname line."""
        self._move(self.after_run)
        self.after_run = None
        self._move(self._funcname(text))

    def change_line(self, kind: str, text: str) -> str | None:
        """The scope's name when this ``+``/``-`` line is the first change in it."""
        first = None if self.named else self.name
        self.named = True
        if kind == "-":
            self.after_run = self._funcname(text) or self.after_run
        return first

    def _funcname(self, text):
        return self.name and _FUNCNAME_LINE.match(text) and hunk_symbol(text[:FALLBACK_CHARS])

    def _move(self, name):
        if name:
            self.name, self.named = name, False
