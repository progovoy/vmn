"""docs/vmn-exp/upgrading.md (plan 43 F9) keeps up with the code: its newest
Formats row names today's format versions and a layout or record-format
change was announced a release ahead."""
import os

from exp_helpers import _PROJECT_ROOT
from upgrading_table import format_table_problems, parse_tables
from vmn_exp.core.index_store_schema import DERIVED_VERSION, RECORDS_VERSION
from vmn_exp.core.record_format import RECORD_FORMAT_VERSION
from vmn_exp.storage.store_marker import LAYOUT

UPGRADING = "docs/vmn-exp/upgrading.md"
CONSTANTS = {"layout": 2, "record_format": 2, "records": 20, "derived": 21}


def _format_row(version, layout=2, record_format=2, records=20, derived=21,
                upgrade="in place", cost="", announced=""):
    return {
        "Version": version,
        "Store layout": str(layout),
        "Record format": str(record_format),
        "Index records": str(records),
        "Index derived": str(derived),
        "Upgrade": upgrade,
        "Cost and operator steps": cost,
        "Announced in": announced,
    }


def test_a_newest_format_row_behind_the_code_constants_is_reported():
    rows = [_format_row("0.1.36", records=19), _format_row("0.1.35", records=19)]

    problems = format_table_problems(rows, CONSTANTS)

    assert len(problems) == 1
    assert "records" in problems[0]


def test_an_in_place_index_bump_needs_only_its_row():
    rows = [_format_row("0.1.36", records=20), _format_row("0.1.35", records=19)]

    assert format_table_problems(rows, CONSTANTS) == []


def test_a_layout_or_record_format_change_without_an_earlier_announcement_is_reported():
    constants = dict(CONSTANTS, layout=3, record_format=3)
    unannounced_layout = [
        _format_row("0.1.40", layout=3, record_format=3, cost="5 min per 100k runs"),
        _format_row("0.1.39"),
    ]
    announced_later = [
        _format_row("0.1.40", layout=3, record_format=3, cost="5 min per 100k runs",
                    announced="0.1.40"),
        _format_row("0.1.39"),
    ]
    announced_earlier = [
        _format_row("0.1.40", layout=3, record_format=3, cost="5 min per 100k runs",
                    announced="0.1.38"),
        _format_row("0.1.39"),
    ]

    assert len(format_table_problems(unannounced_layout, constants)) == 1
    assert len(format_table_problems(announced_later, constants)) == 1
    assert format_table_problems(announced_earlier, constants) == []


def test_a_reload_upgrade_without_a_cost_is_reported():
    rows = [
        _format_row("0.1.40", records=21, upgrade="reload", announced="0.1.38"),
        _format_row("0.1.39"),
    ]

    problems = format_table_problems(rows, dict(CONSTANTS, records=21))

    assert len(problems) == 1
    assert "cost" in problems[0]


def _upgrading_tables():
    with open(os.path.join(_PROJECT_ROOT, UPGRADING), encoding="utf-8") as f:
        return parse_tables(f.read())


def test_upgrading_md_documents_the_current_format_versions():
    code = {"layout": LAYOUT, "record_format": RECORD_FORMAT_VERSION,
            "records": RECORDS_VERSION, "derived": DERIVED_VERSION}
    formats = _upgrading_tables()["formats"]

    assert formats
    assert format_table_problems(formats, code) == []

