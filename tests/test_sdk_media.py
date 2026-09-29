"""``run.log_table`` / ``log_image`` / ``log_histogram`` and the media indexes."""
import io
import json
import sys

import pytest

from vmn_exp.core.media import (
    MAX_HISTOGRAM_STEPS,
    MediaIndex,
    media_counts,
    media_index,
)
from vmn_exp.core.png import encode_png, png_size
from vmn_exp.core.tables import MAX_TABLE_ROWS
from vmn_exp.sdk import reader
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "experiments"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


@pytest.fixture
def run(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    yield run
    run.finish()


def _entries(storage, kind):
    return [e for e in storage.load_merged_log(APP, VERSTR) if e["type"] == kind]


def _artifact(storage, name):
    with open(storage.artifact_local_path(APP, VERSTR, name), "rb") as f:
        return f.read()


# -- tables -----------------------------------------------------------------


def test_log_table_stores_a_columnar_artifact_and_a_small_entry(run, storage):
    run.log_table("preds", [{"y": 1, "label": "a"}, {"y": 0, "label": "b"}], step=3)
    run.finish()
    (entry,) = _entries(storage, "table")
    assert entry["name"] == "preds" and entry["step"] == 3
    assert entry["path"] == "tables/preds/3.json"
    assert entry["rows"] == 2 and entry["columns"] == ["y", "label"]
    doc = json.loads(_artifact(storage, "tables/preds/3.json"))
    assert doc["data"] == [[1, 0], ["a", "b"]]
    assert doc["columns"][0] == {"name": "y", "type": "number"}
    assert not _entries(storage, "artifact")  # one entry per table, not two


def test_log_table_lists_with_columns_and_auto_steps(run, storage):
    run.log_table("t", [[1, 2]], columns=["a", "b"])
    run.log_table("t", [[3, 4]], columns=["a", "b"])
    run.finish()
    assert [e["step"] for e in _entries(storage, "table")] == [0, 1]


def test_log_table_caps_rows_with_a_warning(run, storage, caplog):
    run.log_table("big", [[i] for i in range(MAX_TABLE_ROWS + 1)], columns=["i"])
    run.finish()
    (entry,) = _entries(storage, "table")
    assert entry["rows"] == MAX_TABLE_ROWS and entry["total_rows"] == MAX_TABLE_ROWS + 1
    assert "truncated" in caplog.text


def test_log_table_rejects_a_bad_name(run):
    with pytest.raises(ValueError):
        run.log_table("../x", [{"a": 1}])


# -- images -----------------------------------------------------------------


def test_log_image_from_numpy_writes_a_png(run, storage):
    np = pytest.importorskip("numpy")
    run.log_image("samples", np.zeros((4, 6, 3), dtype=np.uint8), step=2, caption="c")
    run.finish()
    (entry,) = _entries(storage, "image")
    assert entry["path"] == "media/samples/2.png"
    assert (entry["width"], entry["height"], entry["caption"]) == (6, 4, "c")
    data = _artifact(storage, "media/samples/2.png")
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and png_size(data) == (6, 4)


def test_log_image_from_numpy_without_pil(run, storage, monkeypatch):
    np = pytest.importorskip("numpy")
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)
    run.log_image("gray", np.full((2, 3), 0.5))
    run.finish()
    data = _artifact(storage, "media/gray/0.png")
    assert png_size(data) == (3, 2)


def test_log_image_from_a_png_path(run, storage, tmp_path):
    src = tmp_path / "pic.png"
    src.write_bytes(encode_png(bytes(3 * 2 * 2), 2, 2, 3))
    run.log_image("pic", str(src))
    run.finish()
    assert _artifact(storage, "media/pic/0.png") == src.read_bytes()
    assert _entries(storage, "image")[0]["width"] == 2


def test_log_image_from_a_pil_image(run, storage):
    image_mod = pytest.importorskip("PIL.Image")
    run.log_image("pil", image_mod.new("RGB", (5, 3)), step=1)
    run.finish()
    assert png_size(_artifact(storage, "media/pil/1.png")) == (5, 3)


def test_log_image_from_a_jpeg_path_converts_with_pil(run, storage, tmp_path):
    image_mod = pytest.importorskip("PIL.Image")
    src = tmp_path / "pic.jpg"
    image_mod.new("RGB", (4, 4)).save(str(src), format="JPEG")
    run.log_image("jpg", str(src))
    run.finish()
    assert png_size(_artifact(storage, "media/jpg/0.png")) == (4, 4)


class _FakeFigure:
    def savefig(self, path, **kwargs):
        assert kwargs.get("format") == "png"
        with open(path, "wb") as f:
            f.write(encode_png(b"\x00" * 9, 3, 3, 1))


def test_log_image_from_a_figure(run, storage):
    run.log_image("fig", _FakeFigure())
    run.finish()
    assert png_size(_artifact(storage, "media/fig/0.png")) == (3, 3)


def test_log_image_rejects_other_objects(run):
    with pytest.raises(TypeError):
        run.log_image("x", 42)


# -- histograms -------------------------------------------------------------


def test_log_histogram_entry_has_edges_and_counts(run, storage):
    run.log_histogram("w", [0, 1, 2, 3, float("nan")], step=5, bins=3)
    run.finish()
    (entry,) = _entries(storage, "histogram")
    assert entry["name"] == "w" and entry["step"] == 5
    assert len(entry["bins"]) == 4 and entry["counts"] == [1, 1, 2]


def test_log_histogram_of_nothing_finite_records_nothing(run, storage, caplog):
    run.log_histogram("w", [float("nan")])
    run.finish()
    assert not _entries(storage, "histogram")
    assert "finite" in caplog.text


# -- no-op run --------------------------------------------------------------


def test_noop_run_ignores_rich_logging():
    run = NoOpRun("app")
    assert run.log_table("t", [{"a": 1}]) is None
    assert run.log_image("i", object()) is None
    assert run.log_histogram("h", [1, 2]) is None


# -- indexes ----------------------------------------------------------------


def _img(name, step, caption=None):
    return {"type": "image", "name": name, "step": step,
            "path": f"media/{name}/{step}.png", "caption": caption,
            "width": 1, "height": 1}


def test_media_index_groups_by_name_and_step():
    log = [
        _img("a", 1), _img("a", 0), _img("b", 0, "hi"), _img("a", 1, "again"),
        {"type": "table", "name": "t", "step": 0, "path": "tables/t/0.json",
         "rows": 2, "columns": ["x"]},
        {"type": "histogram", "name": "h", "step": 0, "bins": [0, 1], "counts": [2]},
        {"type": "metrics", "values": {"loss": 1}},
    ]
    got = media_index(log)
    assert [s["step"] for s in got["media"]["a"]] == [0, 1]
    assert got["media"]["a"][1]["caption"] == "again"  # the later entry wins
    assert got["media"]["b"][0]["caption"] == "hi"
    assert got["tables"]["t"][0]["rows"] == 2
    assert got["histograms"]["h"][0]["counts"] == [2]
    assert got["histograms_total"] == {"h": 1}


def test_media_index_thins_histogram_steps_keeping_the_ends():
    index = MediaIndex()
    n = MAX_HISTOGRAM_STEPS * 3
    index.extend(
        {"type": "histogram", "name": "h", "step": i, "bins": [0, 1], "counts": [i]}
        for i in range(n)
    )
    got = index.view()
    steps = [s["step"] for s in got["histograms"]["h"]]
    assert len(steps) == MAX_HISTOGRAM_STEPS
    assert steps[0] == 0 and steps[-1] == n - 1
    assert got["histograms_total"]["h"] == n


def test_media_counts():
    log = [_img("a", 0), _img("a", 1), _img("b", 0),
           {"type": "histogram", "name": "h", "step": 0, "bins": [0, 1], "counts": [1]}]
    assert media_counts(log) == {
        "images": {"keys": 2, "entries": 3},
        "tables": {"keys": 0, "entries": 0},
        "histograms": {"keys": 1, "entries": 1},
    }


def test_reader_get_run_exposes_the_media_indexes(run, storage):
    run.log_table("t", [{"a": 1}])
    run.log_histogram("h", [1, 2, 3], bins=2)
    run.finish()
    got = reader.get_run(APP, VERSTR, storage=storage)
    assert got["tables"]["t"][0]["path"] == "tables/t/0.json"
    assert got["histograms"]["h"][0]["counts"] == [1, 2]
    assert got["media"] == {}


def test_png_roundtrip_through_pil_when_logged(run, storage):
    image_mod = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    arr = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    run.log_image("rt", arr)
    run.finish()
    img = image_mod.open(io.BytesIO(_artifact(storage, "media/rt/0.png")))
    assert np.array_equal(np.asarray(img), arr)


def test_auto_steps_continue_after_an_explicit_step_and_skip_failures(run, storage):
    run.log_histogram("h", [1.0], step=4)
    run.log_histogram("h", [1.0])
    with pytest.raises(TypeError):
        run.log_image("i", 42)
    run.log_table("i", [{"a": 1}])
    run.log_image("i", _FakeFigure())
    run.finish()
    assert [e["step"] for e in _entries(storage, "histogram")] == [4, 5]
    assert _entries(storage, "image")[0]["step"] == 0
