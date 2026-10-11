"""A similar index built from the index of an earlier snapshot of the same runs
(``build_index(snapshot, previous=...)``, what a lineage of snapshots does):
a run whose row and side values are the same objects keeps its profile and
postings, so a generation costs what changed — and a snapshot changing nothing
the index reads (a heartbeat: run states only) gets the earlier index itself.
Whatever changed, the result is the index a fresh build gives."""
import random

import pytest
from similar_fixtures import FakeSnapshot, changed, dataset, run
from vmn_exp.core import similar_index
from vmn_exp.core.similar import similar_runs
from vmn_exp.core.similar_index import SimilarIndex, build_index, index_for
from vmn_exp.core.similar_profile import profile_tokens

WORDS = "focal loss label smoothing mixup warmup cosine adam dropout recall".split()


@pytest.fixture
def built(monkeypatch):
    """The verstrs whose profile was built, in order."""
    calls, real = [], similar_index.build_profile

    def counted(row=None, *args, **kwargs):
        calls.append(row.get("verstr"))
        return real(row, *args, **kwargs)

    monkeypatch.setattr(similar_index, "build_profile", counted)
    return calls


def _row(rnd, verstr, parent=None):
    return run(
        verstr, parent=parent, note=" ".join(rnd.sample(WORDS, 2)),
        params={rnd.choice("abcd"): rnd.random()},
        metrics={rnd.choice(["loss", "acc"]): rnd.random()},
        inputs=dataset(f"ds{rnd.randrange(3)}@1", f"sha256:{rnd.randrange(4)}"),
        command=["python", rnd.choice(["train.py", "eval.py"])],
    )


def _features(rnd):
    files = rnd.sample([f"src/m{i}.py" for i in range(6)], 2)
    return changed(files=files, symbols=[f"{files[0]}::f{rnd.randrange(3)}"],
                   commits=[" ".join(rnd.sample(WORDS, 2))])


def _snapshot(rows, features, **kw):
    return FakeSnapshot(rows, features=dict(features), **kw)


def _state(index, rows):
    """Everything a search reads off *index* for *rows*."""
    tokens = set()
    for row in rows:
        tokens |= profile_tokens(index.profile(row["verstr"]))
    return ({t: index.posting(t) for t in sorted(tokens)}, index.bm25.n_docs,
            round(index.bm25.avg_len, 9), {r["verstr"]: index.root(r) for r in rows},
            set(index.parents), [index.row(r["verstr"]) is r for r in rows])


def _base(n=30, seed=1):
    rnd = random.Random(seed)
    rows = [_row(rnd, f"r{i}", parent="r0" if i % 7 == 3 else None) for i in range(n)]
    return rnd, rows, {row["verstr"]: _features(rnd) for row in rows}


def test_a_snapshot_changing_only_run_states_gets_the_earlier_index_itself(built):
    _, rows, features = _base()
    first = build_index(_snapshot(rows, features, run_states={"r1": {"heartbeat": "t1"}}))
    built.clear()
    later = _snapshot(rows, features, run_states={"r1": {"heartbeat": "t2"}})
    assert build_index(later, previous=first) is first
    assert built == []


def test_only_the_changed_and_new_runs_get_a_profile_built(built):
    rnd, rows, features = _base()
    first = build_index(_snapshot(rows, features))
    rows = list(rows)
    rows[4] = dict(rows[4], note="label smoothing now")
    rows.append(_row(rnd, "new"))
    features["new"] = _features(rnd)
    built.clear()
    later = _snapshot(rows, features)
    index = build_index(later, previous=first)
    assert sorted(built) == ["new", "r4"]
    assert _state(index, rows) == _state(SimilarIndex(later), rows)


def test_runs_renumbered_after_a_deletion_keep_their_profiles(built):
    _, rows, features = _base()
    rows = [dict(row, idx=i + 1) for i, row in enumerate(rows)]
    first = build_index(_snapshot(rows, features))
    # The experiment index re-numbers the rows after a deleted one (shallow copies).
    later_rows = [dict(row, idx=i + 1) for i, row in enumerate(rows[:3] + rows[4:])]
    built.clear()
    later = _snapshot(later_rows, features)
    index = build_index(later, previous=first)
    assert built == []
    assert _state(index, later_rows) == _state(SimilarIndex(later), later_rows)


def test_a_run_state_command_change_rebuilds_that_runs_profile(built):
    _, rows, features = _base()
    rows = [dict(row, command=None) for row in rows]
    first = build_index(_snapshot(rows, features, run_states={"r2": {"command": ["a.py"]}}))
    built.clear()
    later = _snapshot(rows, features, run_states={"r2": {"command": ["b.py"]}})
    index = build_index(later, previous=first)
    assert built == ["r2"]
    assert index.posting("cmd:b.py") == ("r2",) and index.posting("cmd:a.py") == ()


def _mutated(rnd, rows, features, step):
    rows, features = list(rows), dict(features)
    for _ in range(rnd.randrange(1, 4)):
        i = rnd.randrange(len(rows))
        kind = rnd.choice(["row", "features", "parent", "drop"])
        verstr = rows[i]["verstr"]
        if kind == "row":
            rows[i] = _row(rnd, verstr, parent=rows[i]["parent"])
        elif kind == "features":
            features[verstr] = _features(rnd)
        elif kind == "parent":
            rows[i] = dict(rows[i], parent=rnd.choice([None, rows[0]["verstr"], "gone"]))
        elif len(rows) > 5:
            del rows[i]
    for k in range(rnd.randrange(3)):
        verstr = f"n{step}.{k}"
        rows.insert(rnd.randrange(len(rows) + 1) if rnd.random() < 0.3 else len(rows),
                    _row(rnd, verstr))
        features[verstr] = _features(rnd)
    if rnd.random() < 0.1:
        rnd.shuffle(rows)
    return rows, features


@pytest.mark.parametrize("seed", range(12))
def test_whatever_changed_the_index_is_the_one_a_fresh_build_gives(seed):
    rnd, rows, features = _base(seed=seed)
    index = build_index(_snapshot(rows, features))
    for step in range(15):
        rows, features = _mutated(rnd, rows, features, step)
        snapshot = _snapshot(rows, features)
        index = build_index(snapshot, previous=index)
        assert _state(index, rows) == _state(SimilarIndex(snapshot), rows), step


def test_a_reordered_snapshot_files_its_trees_as_a_fresh_build_does():
    # Where a parent cycle (a corrupt record) closes depends on the order runs are met in.
    a, b, c = run("a", parent="b"), run("b", parent="c"), run("c", parent="a")
    first = build_index(_snapshot([a, b, c], {}))
    later = _snapshot([b, c, a], {})
    index = build_index(later, previous=first)
    assert _state(index, [b, c, a]) == _state(SimilarIndex(later), [b, c, a])


def test_a_words_only_index_files_no_structured_tokens():
    _, rows, features = _base()
    index = build_index(_snapshot(rows, features), structured=False)
    assert index.structured is False
    assert index.posting("file:src/m0.py") == () and index.posting("pkey:a") == ()
    assert index.posting("w:focal") == SimilarIndex(_snapshot(rows, features)).posting("w:focal")


def test_a_text_search_builds_words_only_and_a_run_search_completes_it(built):
    _, rows, features = _base()
    snapshot = _snapshot(rows, features)
    text = {"row": None, "text": "focal loss", "text_only": True}
    assert similar_runs(snapshot, text)
    assert index_for(snapshot, structured=False).structured is False
    built.clear()
    target = {"row": rows[1], "features": features["r1"]}
    assert similar_runs(snapshot, target)
    assert built == []  # the words index's profiles are reused
    full = index_for(snapshot)
    assert full.structured is True
    assert _state(full, rows) == _state(SimilarIndex(snapshot), rows)
