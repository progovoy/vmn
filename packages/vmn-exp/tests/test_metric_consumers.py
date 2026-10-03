"""Inventory of readers of ``type == "metrics"`` log entries (plan 12 §5.5, phase 0a).

Every such consumer moves to ``SeriesReader``. A new reader of metric log
entries fails here; porting one means deleting its allow-list line.
"""
import re
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("vmn/src", "vmn-exp-sdk/src", "vmn-exp/src")

_METRICS_LITERAL = r"""["']metrics["']"""
_COMPARISON = re.compile(
    rf"[=!]=\s*{_METRICS_LITERAL}|{_METRICS_LITERAL}\s*[=!]=|in\s*\(\s*{_METRICS_LITERAL}\s*,"
)
_ENTRY_KIND = re.compile(r"\b(type|kind|etype)\b")

# file (relative to packages/) -> why it still reads metric entries
ALLOW_LIST = {
    "vmn-exp-sdk/src/vmn_exp/core/values.py": "write-side sanitizing, not a reader",
    "vmn-exp-sdk/src/vmn_exp/core/fold.py": "fold: moves to block/footer summaries (2b)",
    "vmn-exp-sdk/src/vmn_exp/core/sweep/peer_points.py": "sweep median stopping",
    "vmn-exp-sdk/src/vmn_exp/sdk/steps.py": "step seeding on resume",
    "vmn-exp/src/vmn_exp/cli/experiment.py": "vmn-exp show log view (merged_log_view)",
}


def _consumers():
    found = {}
    for root in SOURCE_ROOTS:
        for path in sorted((PACKAGES / root).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if _COMPARISON.search(line) and _ENTRY_KIND.search(line):
                    rel = path.relative_to(PACKAGES).as_posix()
                    found.setdefault(rel, []).append(number)
    return found


def test_every_metric_entry_reader_is_allow_listed():
    unexpected = {f: n for f, n in _consumers().items() if f not in ALLOW_LIST}
    assert unexpected == {}, (
        "new reader of type=='metrics' log entries; read through SeriesReader "
        f"instead (plan 12 §5.5): {unexpected}"
    )


def test_allow_list_has_no_ported_consumers():
    stale = sorted(set(ALLOW_LIST) - set(_consumers()))
    assert stale == [], f"ported consumers still allow-listed, remove them: {stale}"


def test_scanner_flags_a_metric_entry_comparison():
    assert _COMPARISON.search('if entry.get("type") == "metrics":')
    assert not (_COMPARISON.search('if group == "metrics":')
                and _ENTRY_KIND.search('if group == "metrics":'))
