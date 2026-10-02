import json
from pathlib import Path

import pytest

from vmn_exp.core.panel_spec import PANEL_TYPES, json_schema, parse_panel, validate_panel

SCHEMA_FILE = (
    Path(__file__).resolve().parents[1]
    / "webui" / "src" / "reports" / "panelSpec.schema.json"
)

PINNED = {"verstrs": ["0.0.1-dev.abc"]}
LIVE = {"query": "status = \"succeeded\"", "sort": "metrics.loss", "order": "asc", "limit": 20}

VALID = {
    "curves": {"keys": ["val_loss"], "x": {"mode": "metric", "metric": "tokens"},
               "smoothing": 0.6, "log_y": True, "max_points": 500},
    "leaderboard": {"columns": ["metrics.loss"], "params": ["lr"]},
    "bar": {"metric": "loss"},
    "scatter": {"x": "params.lr", "y": "metrics.loss"},
    "parallel": {"columns": ["params.lr", "metrics.loss"]},
    "importance": {"metric": "loss"},
    "grouped": {"group_by": "params.sched", "metric": "loss"},
    "media": {"key": "samples", "step": "last"},
    "table": {"path": "tables/preds/3.json"},
    "histogram": {"key": "grads"},
    "lineage": {"depth": 2},
    "run": {},
}

INVALID = {
    "curves": {"keys": "val_loss"},
    "leaderboard": {"columns": [1]},
    "bar": {},
    "scatter": {"x": "params.lr"},
    "parallel": {"columns": "lr"},
    "importance": {"metric": 3},
    "grouped": {"metric": "loss"},
    "media": {"key": "samples", "step": "first"},
    "table": {},
    "histogram": {"key": None},
    "lineage": {"depth": "deep"},
    "run": {"bogus": 1},
}

SINGLE = {"media", "table", "histogram", "lineage", "run"}


def _spec(kind, extra, runs=None):
    runs = runs or (PINNED if kind in SINGLE else LIVE)
    return {"v": 1, "id": "p1", "type": kind, "app": "trainer", "runs": runs, **extra}


def test_every_type_covered():
    assert set(VALID) == set(PANEL_TYPES) == set(INVALID)


@pytest.mark.parametrize("kind", sorted(VALID))
def test_valid_examples(kind):
    result = validate_panel(_spec(kind, VALID[kind]))
    assert result.ok, result.error
    assert result.spec["type"] == kind


@pytest.mark.parametrize("kind", sorted(INVALID))
def test_invalid_examples(kind):
    result = validate_panel(_spec(kind, INVALID[kind]))
    assert not result.ok
    assert result.error


def test_optional_display_fields():
    assert validate_panel(_spec("bar", {"metric": "m", "title": "T", "height": 300})).ok
    assert not validate_panel(_spec("bar", {"metric": "m", "height": "tall"})).ok


@pytest.mark.parametrize("field", ["v", "id", "type", "app", "runs"])
def test_common_fields_required(field):
    spec = _spec("bar", {"metric": "m"})
    del spec[field]
    assert not validate_panel(spec).ok


def test_version_must_be_one():
    assert not validate_panel({**_spec("bar", {"metric": "m"}), "v": 2}).ok


def test_unknown_type_is_an_error_result():
    result = validate_panel(_spec("sankey", {}))
    assert not result.ok
    assert "sankey" in result.error


def test_non_mapping_is_error_result():
    assert not validate_panel(["x"]).ok


def test_runs_pinned_xor_query():
    assert not validate_panel(_spec("bar", {"metric": "m"}, {**PINNED, **LIVE})).ok
    assert not validate_panel(_spec("bar", {"metric": "m"}, {"limit": 3})).ok
    assert validate_panel(_spec("bar", {"metric": "m"}, PINNED)).ok


def test_runs_query_fields_typed():
    bad = [{"query": "a = 1", "order": "up"}, {"query": "a = 1", "limit": 0},
           {"query": "a = 1", "archived": "yes"}, {"verstrs": []}, {"verstrs": [1]}]
    for runs in bad:
        assert not validate_panel(_spec("bar", {"metric": "m"}, runs)).ok, runs


def test_bad_query_surfaces_offset():
    result = validate_panel(_spec("bar", {"metric": "m"}, {"query": "status = = x"}))
    assert not result.ok
    assert result.query_offset == 9


@pytest.mark.parametrize("kind", sorted(SINGLE))
def test_single_run_types_need_one_verstr(kind):
    two = {"verstrs": ["a", "b"]}
    assert not validate_panel(_spec(kind, VALID[kind], two)).ok
    assert not validate_panel(_spec(kind, VALID[kind], LIVE)).ok


def test_curves_x_metric_mode_needs_metric():
    assert not validate_panel(_spec("curves", {"keys": ["l"], "x": {"mode": "metric"}})).ok
    assert not validate_panel(_spec("curves", {"keys": ["l"], "x": {"mode": "epoch"}})).ok
    assert validate_panel(_spec("curves", {"keys": ["l"], "x": {"mode": "wall"}})).ok


def test_parse_panel_yaml_and_json():
    text = "v: 1\nid: p7\ntype: bar\napp: a\nruns: {verstrs: [x]}\nmetric: loss\n"
    assert parse_panel(text).ok
    assert parse_panel(json.dumps(_spec("bar", {"metric": "m"}))).ok
    assert not parse_panel("a: [").ok


def test_schema_file_matches_generated():
    committed = json.loads(SCHEMA_FILE.read_text())
    assert committed == json_schema()


def test_schema_lists_every_type():
    kinds = {b["properties"]["type"]["const"] for b in json_schema()["oneOf"]}
    assert kinds == set(PANEL_TYPES)
