"""A ``.vmx`` footer describes its keys in write order: a format marker,
the first and last write, the true time bounds and the restart point (where
the steps went back). An old footer, without the marker, kept the step ends
and ``t`` at the min/max step: its keys read right from their columns."""
import glob
import json
import zlib

from vmn_exp.core.fold import fold_metrics, new_fold
from vmn_exp.core.fold_blocks import apply_header, footer_entries
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.metric_index_file import MetricIndexReader, build_index
from vmn_exp.core.metric_index_layout import MAGIC, TAIL
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.core.vmx_write_order import indexed_entries
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
V = "0.0.1-dev.abc.r1"
T0 = 1_700_000_000_000_000

# Steps 0..120 (0.954 at step 120), then a resumed writer from step 0 whose
# last write is 0.989 at step 5.
STEPS = list(range(121)) + list(range(6))
VALUES = [0.5] * 120 + [0.954] + [0.98] * 5 + [0.989]
TS = [1_000_000 * (i + 1) for i in range(len(STEPS))]


def _data(cols):
    return build_index("w", {"best": cols, "lr": Columns([0, 1], [5, 6], [0.1, 0.2])})


def _reader(data):
    return MetricIndexReader(lambda off, n: data[off:off + n], len(data))


def _as_old(data):
    """*data* with the footer an older vmn-exp wrote: no marker, no restart
    point, ends and ``t`` taken after sorting by step."""
    reader = _reader(data)
    footer = reader.footer
    footer.pop("order")
    for name, meta in footer["keys"].items():
        meta.pop("r", None)
        points = reader.points(name)
        ends = [[p["value"], p["step"], p["ts"]] for p in (points[0], points[-1])]
        meta["summary"]["first"], meta["summary"]["last"] = ends
        meta["t"] = [ends[0][2], ends[1][2]]
    packed = zlib.compress(json.dumps(footer, separators=(",", ":")).encode())
    body_end = len(data) - TAIL.size - TAIL.unpack(data[-TAIL.size:])[0]
    return data[:body_end] + packed + TAIL.pack(len(packed), zlib.crc32(packed), MAGIC)


def _key(entries, name):
    return next(e for e in entries if e["k"] == name)


def test_a_new_footer_carries_its_format_marker():
    assert _reader(_data(Columns(STEPS, TS, VALUES))).footer["order"] == "write"


def test_t_is_the_true_time_bounds():
    # The highest step (120) is not the latest write: t ends at the last write.
    meta = _reader(_data(Columns(STEPS, TS, VALUES))).footer["keys"]["best"]
    assert meta["t"] == [TS[0], TS[-1]]


def test_t_bounds_ignore_the_step_order():
    cols = Columns([2, 0, 1], [30, 10, 20], [1.0, 2.0, 3.0])
    assert _reader(_data(cols)).footer["keys"]["best"]["t"] == [10, 30]


def test_the_restart_point_is_written_at_compaction():
    keys = _reader(_data(Columns(STEPS, TS, VALUES))).footer["keys"]
    assert keys["best"]["r"] == [120, 5]
    assert "r" not in keys["lr"]


def test_a_new_footer_reads_as_written():
    reader = _reader(_data(Columns(STEPS, TS, VALUES)))
    assert indexed_entries(reader) == footer_entries(reader.footer)


def test_an_old_footer_reads_its_write_ends_from_its_columns():
    reader = _reader(_as_old(_data(Columns(STEPS, TS, VALUES))))
    assert reader.footer["keys"]["best"]["summary"]["last"] == [0.954, 120, TS[120]]
    best = _key(indexed_entries(reader), "best")
    assert best["first"] == [0.5, 0, TS[0]]
    assert best["last"] == [0.989, 5, TS[-1]]
    assert best["t"] == [TS[0], TS[-1]]
    assert best["r"] == [120, 5]
    assert "r" not in _key(indexed_entries(reader), "lr")


def test_an_old_footer_folds_the_last_write():
    reader = _reader(_as_old(_data(Columns(STEPS, TS, VALUES))))
    fold = apply_header(new_fold(), "w", 0, {"keys": indexed_entries(reader)})
    assert fold_metrics(fold)[0]["best"] == 0.989


def test_an_old_step_less_key_reads_unchanged():
    data = build_index("w", {"cpu": Columns(None, [10, 20, 30], [1.0, 2.0, 3.0])})
    reader = _reader(_as_old(data))
    cpu = _key(indexed_entries(reader), "cpu")
    assert (cpu["first"], cpu["last"], cpu["t"]) == ([1.0, None, 10], [3.0, None, 30], [10, 30])
    assert "r" not in cpu


def _compacted_run(tmp_path, old=False):
    """A run whose ``best`` restarted its steps, compacted to a ``.vmx`` (with
    *old*, rewritten with an older vmn-exp's footer)."""
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    w = MetricWriter(st, APP, V, "w")
    for step, ts, value in zip(STEPS, TS, VALUES):
        w.add("best", value, step=step, ts_us=T0 + ts)
    w.flush()
    assert compact_writer(st, APP, V, "w")
    if old:
        [vmx] = glob.glob(str(tmp_path / "**" / "*.vmx"), recursive=True)
        with open(vmx, "rb") as f:
            data = f.read()
        with open(vmx, "wb") as f:
            f.write(_as_old(data))
    return st


def test_an_old_footers_rewind_check_reads_its_true_earliest_write(tmp_path):
    # Steps 5..7, a rewind to step 6, then steps 0..1: the old footer's t[0]
    # was the time of step 0 (after the rewind), so the rewind seemed not to
    # reach the file and step 7's 100.0 stayed in the max.
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    w = MetricWriter(st, APP, V, "w")
    for step, sec, value in ((5, 1, 1.0), (6, 2, 2.0), (7, 3, 100.0), (0, 5, 10.0), (1, 6, 11.0)):
        w.add("x", value, step=step, ts_us=T0 + sec * 1_000_000)
    w.flush()
    assert compact_writer(st, APP, V, "w")
    [vmx] = glob.glob(str(tmp_path / "**" / "*.vmx"), recursive=True)
    with open(vmx, "rb") as f:
        data = f.read()
    with open(vmx, "wb") as f:
        f.write(_as_old(data))
    st.append_log_entry(APP, V, "w", {"timestamp": us_to_iso(T0 + 4_000_000),
                                       "type": "rewind", "step": 6})
    [row] = ExperimentIndex(st, APP).refresh().rows()
    assert row["metric_summary"]["x"]["max"] == 11.0
    assert row["metrics"]["x"] == 11.0


def test_the_index_folds_an_old_footer_to_the_last_write(tmp_path):
    st = _compacted_run(tmp_path, old=True)
    [row] = ExperimentIndex(st, APP).refresh().rows()
    assert row["metrics"]["best"] == 0.989
