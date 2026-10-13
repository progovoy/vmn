#!/usr/bin/env python3
"""The changed files of a run's patch text, for the ``/patch`` endpoint.

The text is ``show --patch``'s: ``=== <label> ===`` sections (``working_tree``,
``local_commits``, ``deps/<dep>/<kind>``) of unified diffs and format-patch
mboxes. Each section is read by the run-features patch parser, which knows
which ``+``/``-`` lines are inside a hunk (not a commit message, a diffstat
or format-patch's ``-- `` signature); this one only counts them per path.
"""
import re

from vmn_exp.core.features_patch import _Parser

_SECTION = re.compile(r"^=== (.+) ===$", re.MULTILINE)


class _Counter(_Parser):
    """The features parser, counting each path's added/removed lines."""

    def __init__(self, prefix, counts):
        super().__init__(prefix, frozenset())
        self.counts = counts

    def _change_line(self, kind, text):
        counted = self.counts.setdefault(self.path, {"path": self.path, "added": 0, "removed": 0})
        counted["added" if kind == "+" else "removed"] += 1

    def _end_header(self):
        super()._end_header()
        if self.path is not None:
            self.counts.setdefault(self.path, {"path": self.path, "added": 0, "removed": 0})


def _sections(text):
    """``(dep prefix, section text)`` per ``=== label ===`` section."""
    marks = list(_SECTION.finditer(text))
    for mark, after in zip(marks, marks[1:] + [None]):
        label = mark.group(1)
        prefix = label.rsplit("/", 1)[0] if label.startswith("deps/") else ""
        yield prefix, text[mark.end() + 1:after.start() if after else len(text)]


def patch_files(text):
    """``[{"path", "added", "removed"}]`` in order of appearance, summed
    over the sections a path appears in; [] without text."""
    counts = {}
    for prefix, section in _sections(text or ""):
        parser = _Counter(prefix, counts)
        for line in section.split("\n"):
            parser.feed(line[:-1] if line.endswith("\r") else line)
        parser.close()
    return list(counts.values())
