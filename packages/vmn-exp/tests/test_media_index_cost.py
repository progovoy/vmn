"""What a live run's media index costs while its log grows.

Histograms are thinned as they arrive — never more than about twice the
served :data:`MAX_HISTOGRAM_STEPS` held — and a view only rebuilds the names
that gained entries since the last one.
"""
import gc
import weakref

from vmn_exp.core.media import MAX_HISTOGRAM_STEPS, MediaIndex


class _Counts(list):
    """A list that can be weakly referenced, to see which histograms are held."""


def _hist(step, counts=None):
    return {"type": "histogram", "name": "h", "step": step, "bins": [0, 1],
            "counts": counts if counts is not None else [step]}


def _img(name, step):
    return {"type": "image", "name": name, "step": step,
            "path": f"media/{name}/{step}.png", "width": 1, "height": 1}


def test_histogram_steps_are_thinned_on_ingest():
    index = MediaIndex()
    refs = []
    n = MAX_HISTOGRAM_STEPS * 50
    for step in range(n):
        counts = _Counts([step])
        refs.append(weakref.ref(counts))
        index.add([_hist(step, counts)])
        del counts
    gc.collect()

    held = sum(1 for r in refs if r() is not None)
    assert held <= 2 * MAX_HISTOGRAM_STEPS + 2
    got = index.view()
    steps = [s["step"] for s in got["histograms"]["h"]]
    assert len(steps) == MAX_HISTOGRAM_STEPS
    assert steps[0] == 0 and steps[-1] == n - 1
    assert steps == sorted(steps)
    assert got["histograms_total"]["h"] == n


def test_thinned_histograms_still_count_distinct_steps_and_take_relogs():
    index = MediaIndex()
    index.add([_hist(s) for s in range(1000)])
    index.add([_hist(0, [-1]), _hist(999, [-9]), _hist(500)])  # re-logged steps
    got = index.view()
    assert got["histograms_total"]["h"] == 1000
    assert got["histograms"]["h"][0]["counts"] == [-1]
    assert got["histograms"]["h"][-1]["counts"] == [-9]


def test_out_of_order_histogram_steps_are_served_in_step_order():
    index = MediaIndex()
    index.add([_hist(s) for s in (5, 1, 9, 3)])
    got = index.view()["histograms"]["h"]
    assert [s["step"] for s in got] == [1, 3, 5, 9]


def test_a_view_rebuilds_only_the_names_that_changed():
    index = MediaIndex()
    index.add([_img("a", 0), _img("b", 0)])
    first = index.view()
    index.add([_img("b", 1)])
    second = index.view()

    assert second["media"]["a"] is first["media"]["a"]
    assert [s["step"] for s in second["media"]["b"]] == [0, 1]
    assert [s["step"] for s in first["media"]["b"]] == [0]  # an old view is fixed
