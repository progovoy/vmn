"""docs/plans/README.md links every plan file, and each row's status word is
the word on the linked plan's own Status line (plan 43 F8)."""
import glob
import os

from exp_helpers import _PROJECT_ROOT
from plans_index import plans_index_problems

PLANS_DIR = os.path.join(_PROJECT_ROOT, "docs", "plans")

_HEADER = "| # | Feature | Status | Plan |\n|---|---|---|---|\n"


def _index(*rows):
    return _HEADER + "".join(f"| {n} | x | {status} | [{name}]({name}) |\n" for n, status, name in rows)


def test_a_plan_file_the_index_does_not_link_is_reported():
    index = _index(("1", "**done**", "01-a.md"))
    files = {"01-a.md": "Status: **done** (2026-10-01).\n", "02-b.md": "Status: **proposal**.\n"}
    assert plans_index_problems(index, files) == ["02-b.md: not linked from the index"]


def test_a_done_row_over_a_proposal_status_line_is_reported():
    index = _index(("19", "**done** (`ui/routes_shell.py`)", "19-shell.md"))
    files = {"19-shell.md": "# Plan 19\n\nStatus: **proposal** (2026-10-12). Three proposals\n"}
    assert plans_index_problems(index, files) == ["19-shell.md: row says 'done', Status line says 'proposal'"]


def test_a_proposal_row_over_a_done_status_line_is_reported():
    index = _index(("17", "proposal", "17-goto.md"))
    files = {"17-goto.md": "Status: **done 2026-10-10** (commits `fcfd49c7`).\n"}
    assert plans_index_problems(index, files) == ["17-goto.md: row says 'proposal', Status line says 'done'"]


def test_a_plan_file_without_a_status_line_is_reported():
    index = _index(("1", "**done**", "01-a.md"))
    files = {"01-a.md": "# Plan 1\n\nNo status here.\n"}
    assert plans_index_problems(index, files) == ["01-a.md: row says 'done', Status line says None"]


def test_agreeing_rows_including_in_progress_and_done_except_are_clean():
    index = _index(
        ("23", "**in progress** (Jobs view)", "23-scale.md"),
        ("31", "**done** except §3 (on hold)", "31-fgm.md"),
    ) + "| 4b | auto-step | **done** | same file |\n"
    files = {
        "23-scale.md": "Status: **in progress** (2026-10-14).\n",
        "31-fgm.md": "Status: **done except §3** (2026-11-07).\n",
    }
    assert plans_index_problems(index, files) == []


def test_the_plans_index_agrees_with_the_plan_files():
    files = {}
    for path in glob.glob(os.path.join(PLANS_DIR, "[0-9]*.md")):
        with open(path, encoding="utf-8") as f:
            files[os.path.basename(path)] = f.read()
    with open(os.path.join(PLANS_DIR, "README.md"), encoding="utf-8") as f:
        index = f.read()
    assert plans_index_problems(index, files) == []
