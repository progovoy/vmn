"""The ``gc`` section: how often and for how long the cyclic collector
stopped the process, from ``gc.callbacks`` (always on, a few tuples per
collection). On a free-threaded build every automatic collection stops the
whole process and scans the whole heap, so a minutes-long stall there is
either a GC pause on record here or something else."""
import gc

import pytest

from vmn_exp.ui import diag
from vmn_exp.ui.diag import gc_pauses, registry


@pytest.fixture(autouse=True)
def _isolated_sections(monkeypatch):
    monkeypatch.setattr(registry, "_SECTIONS", dict(registry._SECTIONS))


@pytest.fixture
def callbacks(monkeypatch):
    """The interpreter's own ``gc.callbacks`` list (it keeps a reference to
    it, so rebinding the attribute would not reach it), restored after."""
    saved = list(gc.callbacks)
    monkeypatch.setattr(gc_pauses, "PAUSES", gc_pauses.GcPauses())
    gc.callbacks[:] = [cb for cb in saved if cb is not gc_pauses.PAUSES.callback]
    yield gc.callbacks
    gc.callbacks[:] = saved


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _pauses(recent=4):
    clock, wall = _Clock(), _Clock()
    wall.now = 1_700_000_000.0
    return gc_pauses.GcPauses(recent=recent, clock=clock, wall=wall), clock, wall


def _collect(pauses, clock, sec, generation=2, collected=0, uncollectable=0):
    pauses.callback("start", {"generation": generation})
    clock.now += sec
    pauses.callback("stop", {"generation": generation, "collected": collected,
                             "uncollectable": uncollectable})


def test_a_collection_is_recorded_with_its_pause_and_counts():
    pauses, clock, wall = _pauses()
    _collect(pauses, clock, 0.25, generation=2, collected=7, uncollectable=1)
    stats = pauses.stats()
    assert stats["collections"] == 1
    assert stats["total_ms"] == pytest.approx(250)
    assert stats["max_ms"] == pytest.approx(250)
    assert stats["max_at"] == wall.now and stats["max_generation"] == 2
    assert stats["collected"] == 7 and stats["uncollectable"] == 1
    [recent] = stats["recent"]
    assert recent == {"at": wall.now, "ms": pytest.approx(250), "generation": 2,
                      "collected": 7, "uncollectable": 1}


def test_totals_and_the_worst_pause_per_generation():
    pauses, clock, _ = _pauses()
    _collect(pauses, clock, 0.001, generation=0)
    _collect(pauses, clock, 0.003, generation=0)
    _collect(pauses, clock, 2.0, generation=2)
    stats = pauses.stats()
    assert stats["collections"] == 3 and stats["max_ms"] == pytest.approx(2000)
    assert stats["by_generation"]["0"] == {"collections": 2, "total_ms": pytest.approx(4),
                                           "max_ms": pytest.approx(3)}
    assert stats["by_generation"]["2"]["collections"] == 1


def test_the_recent_pauses_are_bounded_and_newest_last():
    pauses, clock, _ = _pauses(recent=4)
    for i in range(10):
        _collect(pauses, clock, 0.001 * (i + 1), generation=0)
    stats = pauses.stats()
    assert stats["collections"] == 10
    assert [r["ms"] for r in stats["recent"]] == pytest.approx([7, 8, 9, 10])


def test_a_stop_without_its_start_is_ignored():
    pauses, _, _ = _pauses()
    pauses.callback("stop", {"generation": 0, "collected": 0, "uncollectable": 0})
    assert pauses.stats()["collections"] == 0


def test_install_registers_the_callback_once(callbacks):
    gc_pauses.install()
    gc_pauses.install()
    assert callbacks.count(gc_pauses.PAUSES.callback) == 1


def test_a_real_collection_shows_in_the_section(callbacks):
    gc_pauses.install()
    gc.collect()
    section = gc_pauses.gc_section()
    assert section["collections"] >= 1
    assert section["recent"][-1]["generation"] == 2


def test_the_section_says_how_the_collector_is_set_up():
    section = gc_pauses.gc_section()
    assert section["enabled"] == gc.isenabled()
    assert section["threshold"] == list(gc.get_threshold())
    assert section["freeze_count"] == gc.get_freeze_count()
    assert section["gil_enabled"] in (True, False)
    assert section["allocator"]["allocated_blocks"] > 0


def test_the_section_says_whether_the_free_threaded_policy_schedules_collections():
    from vmn_exp.core.gc_policy import POLICY

    assert gc_pauses.gc_section()["policy"] == POLICY.stats()


def test_a_free_threaded_build_allocates_with_mimalloc():
    info = gc_pauses.allocator_info(environ={"MIMALLOC_PURGE_DELAY": "0", "HOME": "/h"},
                                    free_threaded=True)
    assert info["name"] == "mimalloc"
    assert info["env"] == {"MIMALLOC_PURGE_DELAY": "0"}


def test_a_gil_build_names_its_allocator_from_pythonmalloc():
    assert gc_pauses.allocator_info(environ={}, free_threaded=False)["name"] == "pymalloc"
    info = gc_pauses.allocator_info(environ={"PYTHONMALLOC": "mimalloc"}, free_threaded=False)
    assert info["name"] == "mimalloc" and info["env"] == {"PYTHONMALLOC": "mimalloc"}


def test_the_default_sections_include_gc_and_record_pauses(callbacks):
    diag.install_default_sections()
    assert "gc" in registry._SECTIONS
    assert gc_pauses.PAUSES.callback in callbacks
