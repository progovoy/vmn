"""Pure check of docs/plans/README.md against the plan files: every plan file
is linked, a row's first status word is the first word of the linked
plan's own ``Status:`` line, and every plan from 37 on carries a
``Solo impact:`` line (plan 43 F13)."""
import re

from doc_links import unlinked_docs

_ROW_LINK = re.compile(r"\]\(([^)#\s]+\.md)")
_STATUS_LINE = re.compile(r"^Status:\s*(.*)$", re.MULTILINE)
_WORD = re.compile(r"[a-z]+")
_SOLO_LINE = re.compile(r"^Solo impact:", re.MULTILINE)
_PLAN_NUMBER = re.compile(r"^(\d+)-")
FIRST_SOLO_PLAN = 37


def _first_word(text):
    match = _WORD.search(text.replace("*", "").lower())
    return match.group(0) if match else None


def _status_word(plan_text):
    match = _STATUS_LINE.search(plan_text)
    return _first_word(match.group(1)) if match else None


def _needs_solo_line(name):
    number = _PLAN_NUMBER.match(name)
    return bool(number) and int(number.group(1)) >= FIRST_SOLO_PLAN


def _rows(index_text):
    """(status cell, linked plan files) for each table row of the index."""
    for line in index_text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 4:
            yield cells[2], _ROW_LINK.findall(cells[-1])


def plans_index_problems(index_text, plans):
    """Problems as text: plan files in *plans* (filename -> text) the index
    never links, plans from 37 on without a ``Solo impact:`` line, and rows
    whose status word differs from a linked file's."""
    problems = [f"{name}: not linked from the index" for name in unlinked_docs(index_text, plans)]
    problems += [f"{name}: no 'Solo impact:' line" for name in sorted(plans)
                 if _needs_solo_line(name) and not _SOLO_LINE.search(plans[name])]
    for status, linked in _rows(index_text):
        row_word = _first_word(status)
        for name in (name for name in linked if name in plans):
            file_word = _status_word(plans[name])
            if file_word != row_word:
                problems.append(f"{name}: row says {row_word!r}, Status line says {file_word!r}")
    return problems
