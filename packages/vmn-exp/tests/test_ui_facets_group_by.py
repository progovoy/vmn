"""Plan 22 G2: the facets carry what the board's Group by menu offers — tag
keys, how many distinct values each param has (capped: the menu only needs
"<= 20 or more") and how many runs have a parent (the default grouping)."""
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.leaderboard_facets import DISTINCT_CAP
from vmn_exp.ui.readers.experiments import facets

APP = "app"


def _row(i, params=None, parent=None, tags=None, archived=False):
    verstr = f"1.0.0-dev.r{i:04d}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i % 60:02d}.{i:06d}Z"}
    if parent is not None:
        meta["parent"] = f"1.0.0-dev.r{parent:04d}"
    if archived:
        meta["archived"] = True
    log = [{"timestamp": "t", "type": "create", "params": params or {}}]
    row = experiment_row(i + 1, meta, log)
    if tags:
        row["tags"] = dict(tags)
    return row


def _snap(rows, generation=1):
    return IndexSnapshot.build(APP, generation, rows, {})


def test_facets_name_the_tag_keys():
    rows = [_row(0, tags={"team": "a"}), _row(1, tags={"team": "b", "stage": "x"}), _row(2)]
    assert facets(rows)["tag_keys"] == ["stage", "team"]


def test_facets_count_distinct_param_values_up_to_one_past_the_cap():
    rows = [_row(i, params={"opt": ["adam", "sgd"][i % 2], "seed": i, "lr": 0.1})
            for i in range(DISTINCT_CAP + 5)]
    assert facets(rows)["param_values"] == {"lr": 1, "opt": 2, "seed": DISTINCT_CAP + 1}


def test_unhashable_param_values_are_counted_too():
    rows = [_row(0, params={"layers": [1, 2]}), _row(1, params={"layers": [1, 2]}),
            _row(2, params={"layers": [3]})]
    assert facets(rows)["param_values"] == {"layers": 2}


def test_facets_count_the_runs_with_a_parent():
    rows = [_row(0), _row(1, parent=0), _row(2, parent=0), _row(3)]
    assert facets(rows)["parented"] == 2
    assert facets(rows[:1])["parented"] == 0


def test_the_cache_answers_what_a_full_scan_does_across_generations():
    cache = lb.LeaderboardCache()
    rows = [_row(i, params={"opt": ["adam", "sgd"][i % 2]}, parent=0 if i else None,
                 tags={"team": "a"} if i % 3 == 0 else None) for i in range(12)]
    first = _snap(rows)
    assert cache.facets(first) == facets(rows)

    # A new run with a new value and tag, one run gone, one now archived.
    rows2 = rows[1:] + [_row(12, params={"opt": "lion"}, tags={"stage": "x"}, parent=3)]
    rows2[4] = _row(5, params={"opt": "sgd"}, parent=0, archived=True)
    second = _snap(rows2, generation=2)
    visible = [r for r in rows2 if not r.get("archived")]
    got = cache.facets(second)
    assert got == facets(visible)
    assert got["param_values"] == {"opt": 3}
    assert got["tag_keys"] == ["stage", "team"]
    assert got["parented"] == len(visible)


def test_a_value_that_leaves_lowers_the_count():
    cache = lb.LeaderboardCache()
    rows = [_row(0, params={"opt": "adam"}), _row(1, params={"opt": "sgd"})]
    cache.facets(_snap(rows))
    assert cache.facets(_snap(rows[:1], generation=2))["param_values"] == {"opt": 1}
