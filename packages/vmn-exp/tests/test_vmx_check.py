"""The light check of a run folded from records 19: it reads only the run's
``.vmx`` footers (and an old footer's timestamps column) and says whether
its fold must be read again — an old footer out of write order, or a metric
whose last write is below its highest step."""
import glob

from test_vmx_write_order import APP, STEPS, T0, TS, V, VALUES, _as_old

from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.vmx_check import needs_refold
from vmn_exp.snapshot import LocalSnapshotStorage


def _run(tmp_path, steps, old=False, values=None):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    w = MetricWriter(st, APP, V, "w")
    for i, step in enumerate(steps):
        w.add("best", (values or [0.5] * len(steps))[i], step=step, ts_us=T0 + TS[i])
    w.flush()
    assert compact_writer(st, APP, V, "w")
    if old:
        [vmx] = glob.glob(str(tmp_path / "**" / "*.vmx"), recursive=True)
        with open(vmx, "rb") as f:
            data = f.read()
        with open(vmx, "wb") as f:
            f.write(_as_old(data))
    return st


def _objects(st):
    return {name: size for objs in st.metric_objects(APP, V).values()
            for name, size in objs if is_indexed_file(name)}


def _reads(st, monkeypatch):
    seen = []
    original = st.read_range

    def spy(app_name, verstr, name, offset, length):
        seen.append(length)
        return original(app_name, verstr, name, offset, length)

    monkeypatch.setattr(st, "read_range", spy)
    return seen


def test_rising_steps_need_no_refold_old_footer_or_new(tmp_path):
    for old in (False, True):
        st = _run(tmp_path / str(old), list(range(50)), old=old)
        assert needs_refold(st, (APP, V), _objects(st)) is False


def test_a_last_write_below_the_highest_step_needs_a_refold(tmp_path):
    for old in (False, True):
        st = _run(tmp_path / str(old), STEPS, old=old, values=VALUES)
        assert needs_refold(st, (APP, V), _objects(st)) is True


def test_a_new_footer_costs_one_read(tmp_path, monkeypatch):
    st = _run(tmp_path, list(range(50)))
    reads = _reads(st, monkeypatch)
    needs_refold(st, (APP, V), _objects(st))
    assert len(reads) == 1


def test_an_object_gone_since_listed_needs_a_refold(tmp_path):
    st = _run(tmp_path, list(range(5)))
    assert needs_refold(st, (APP, V), {"metrics/w@000000-000009.vmx": 100}) is True
