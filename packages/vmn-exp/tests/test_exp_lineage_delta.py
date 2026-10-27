"""A :class:`LineageIndex` moved to the next index generation by its row
delta is the index a full build of that generation gives, and leaves the
previous generation's index as it was."""
import copy

from vmn_exp.core.lineage import LineageIndex, artifact_ref_uri

A, B, C, D = ("a" * 64, "b" * 64, "c" * 64, "e" * 64)


def _row(verstr, idx, inputs=None, outputs=None):
    return {"verstr": verstr, "idx": idx, "inputs": inputs or {}, "outputs": outputs or {}}


def _out(path, digest):
    return {path: {"path": path, "digest": digest}}


def _inp(name, digest, uri="s3://b/k"):
    return {name: {"uri": uri, "digest": digest}}


def _maps(index):
    return index.rows, index.producers, index.digest_consumers, index.uri_consumers


def _old_rows():
    return [
        _row("p", 1, outputs=_out("d.csv", A)),
        _row("t1", 2, inputs=_inp("d", A), outputs=_out("m.pkl", B)),
        _row("t2", 3, inputs=_inp("d", A)),
        _row("t3", 4, inputs=_inp("d", A), outputs=_out("m.pkl", C)),
        _row("t4", 5, inputs={**_inp("d", A), "m": {"uri": artifact_ref_uri("app", "t1", "m.pkl")}},
             outputs=_out("y", A)),
    ]


def _moved(old, new):
    prev = LineageIndex(old)
    before = copy.deepcopy(_maps(prev))
    joined = [row for i, row in enumerate(new) if i >= len(old) or row is not old[i]]
    left = [row for i, row in enumerate(old) if i >= len(new) or row is not new[i]]
    moved = LineageIndex.moved(prev, new, None, joined, left)
    assert _maps(prev) == before
    return moved


def test_moved_index_equals_a_full_build():
    old = _old_rows()
    new = list(old)
    new[1] = _row("t1", 2, inputs=_inp("d", D), outputs=_out("m.pkl", B))  # input changed
    new[2] = dict(old[2])  # re-folded, same links
    new[3] = _row("t3", 4, inputs=_inp("d", A), outputs={**_out("m.pkl", C), **_out("x", A)})
    new.append(_row("t5", 6, inputs=_inp("m", C), outputs=_out("d.csv", A)))
    assert _maps(_moved(old, new)) == _maps(LineageIndex(new))


def test_moved_index_drops_rows_that_left():
    old = _old_rows()
    new = old[:3]
    assert _maps(_moved(old, new)) == _maps(LineageIndex(new))


def test_moved_index_keeps_storage_order_for_a_row_changed_in_place():
    old = _old_rows()
    new = list(old)
    new[0] = _row("p", 1, outputs={**_out("e.csv", A), **_out("d.csv", A)})
    new[1] = _row("t1", 2, inputs=_inp("d", A), outputs={**_out("m.pkl", B), **_out("copy", A)})
    moved = _moved(old, new)
    assert moved.producers[A] == [("p", "e.csv"), ("p", "d.csv"), ("t1", "copy"), ("t4", "y")]
    assert _maps(moved) == _maps(LineageIndex(new))
