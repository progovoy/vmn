"""Rich-logging building blocks: the stdlib PNG encoder, histograms and tables."""
import io
import math
import struct
import sys
import zlib

import pytest

from vmn_exp.core import histogram as hist_mod
from vmn_exp.core.histogram import histogram
from vmn_exp.core.png import array_to_png, encode_png, png_size
from vmn_exp.core.tables import MAX_TABLE_ROWS, table_document, table_page

# -- PNG encoder ------------------------------------------------------------


def _chunks(data):
    pos, found = 8, []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        found.append((kind, body))
        pos += 12 + length
    return found


def test_encode_png_writes_signature_ihdr_and_a_zlib_idat():
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 10, 20, 30])  # 2x2 RGB
    data = encode_png(pixels, width=2, height=2, channels=3)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = _chunks(data)
    kinds = [k for k, _ in chunks]
    assert kinds[0] == b"IHDR" and kinds[-1] == b"IEND"
    width, height, depth, color = struct.unpack(">IIBB", chunks[0][1][:10])
    assert (width, height, depth, color) == (2, 2, 8, 2)
    raw = zlib.decompress(b"".join(b for k, b in chunks if k == b"IDAT"))
    # Each scanline: filter byte 0 then the row's pixels.
    assert raw == b"\x00" + pixels[:6] + b"\x00" + pixels[6:]
    assert png_size(data) == (2, 2)


@pytest.mark.parametrize("channels,color", [(1, 0), (2, 4), (3, 2), (4, 6)])
def test_encode_png_color_types(channels, color):
    data = encode_png(bytes(channels * 3), width=3, height=1, channels=channels)
    assert _chunks(data)[0][1][9] == color


def test_encode_png_rejects_a_size_mismatch():
    with pytest.raises(ValueError):
        encode_png(b"\x00" * 5, width=2, height=2, channels=1)


def test_encoded_png_opens_with_pil():
    image_mod = pytest.importorskip("PIL.Image")
    pixels = bytes(range(0, 48))  # 4x4 RGB
    img = image_mod.open(io.BytesIO(encode_png(pixels, 4, 4, 3)))
    assert img.size == (4, 4) and img.mode == "RGB"
    assert img.getpixel((1, 0)) == (3, 4, 5)


def test_array_to_png_takes_uint8_and_unit_floats():
    np = pytest.importorskip("numpy")
    gray = np.array([[0, 128], [255, 7]], dtype=np.uint8)
    assert _raw_rows(array_to_png(gray)) == [b"\x00\x80", b"\xff\x07"]
    floats = np.array([[0.0, 0.5], [1.0, 2.0]])  # clipped to 0..1
    assert _raw_rows(array_to_png(floats)) == [b"\x00\x80", b"\xff\xff"]
    rgb = np.zeros((1, 2, 3), dtype=np.uint8)
    rgb[0, 1] = (1, 2, 3)
    data = array_to_png(rgb)
    assert _chunks(data)[0][1][9] == 2
    assert _raw_rows(data) == [b"\x00\x00\x00\x01\x02\x03"]
    assert png_size(array_to_png(np.zeros((5, 7, 1)))) == (7, 5)


def test_array_to_png_rejects_other_shapes():
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        array_to_png(np.zeros((2, 2, 5)))
    with pytest.raises(ValueError):
        array_to_png(np.zeros(4))


def _raw_rows(data):
    chunks = _chunks(data)
    width, height = struct.unpack(">II", chunks[0][1][:8])
    raw = zlib.decompress(b"".join(b for k, b in chunks if k == b"IDAT"))
    stride = len(raw) // height
    return [raw[i * stride + 1 : (i + 1) * stride] for i in range(height)]


# -- histograms -------------------------------------------------------------


def test_histogram_edges_and_counts():
    got = histogram([0, 1, 2, 3, 4], bins=4)
    assert got["bins"] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert got["counts"] == [1, 1, 1, 2]  # the last bin includes its right edge


def test_histogram_drops_non_finite_values():
    got = histogram([1.0, float("nan"), float("inf"), 3.0, -float("inf")], bins=2)
    assert got["counts"] == [1, 1]
    assert all(math.isfinite(e) for e in got["bins"])


def test_histogram_of_a_constant_widens_the_range():
    got = histogram([2.0, 2.0], bins=2)
    assert got["bins"] == [1.5, 2.0, 2.5]
    assert sum(got["counts"]) == 2


def test_histogram_of_nothing_finite_is_none():
    assert histogram([float("nan")]) is None
    assert histogram([]) is None


def test_histogram_needs_a_positive_bin_count():
    with pytest.raises(ValueError):
        histogram([1, 2], bins=0)


def test_pure_python_histogram_matches_numpy(monkeypatch):
    np = pytest.importorskip("numpy")
    values = np.random.RandomState(0).normal(size=1000)
    with_numpy = histogram(values, bins=16)
    monkeypatch.setitem(sys.modules, "numpy", None)
    without = histogram(values.tolist(), bins=16)
    assert without["counts"] == with_numpy["counts"]
    assert without["bins"] == pytest.approx(with_numpy["bins"])
    assert hist_mod._numpy() is None


def test_histogram_takes_a_2d_numpy_array():
    np = pytest.importorskip("numpy")
    got = histogram(np.ones((3, 4)), bins=1)
    assert got["counts"] == [12]


# -- tables -----------------------------------------------------------------


def test_table_from_dicts_is_columnar_with_types():
    doc, total = table_document([{"a": 1, "b": "x"}, {"a": 2.5, "c": True}])
    assert total == 2
    assert doc["columns"] == [
        {"name": "a", "type": "number"},
        {"name": "b", "type": "string"},
        {"name": "c", "type": "bool"},
    ]
    assert doc["data"] == [[1, 2.5], ["x", None], [None, True]]
    assert doc["rows"] == 2 and doc["truncated"] is False


def test_table_from_lists_needs_columns():
    doc, _ = table_document([[1, "a"], [2, "b"]], columns=["n", "s"])
    assert [c["name"] for c in doc["columns"]] == ["n", "s"]
    assert doc["data"] == [[1, 2], ["a", "b"]]
    with pytest.raises(ValueError):
        table_document([[1, 2]])
    with pytest.raises(ValueError):
        table_document([[1, 2, 3]], columns=["a", "b"])


def test_table_mixed_and_non_json_cells():
    doc, _ = table_document([[1, float("nan")], ["x", object]], columns=["m", "o"])
    assert doc["columns"][0]["type"] == "mixed"
    assert doc["data"][1][0] is None  # NaN is not JSON
    assert isinstance(doc["data"][1][1], str)


class _FakeFrame:
    """Just what pandas' DataFrame offers the table code."""

    columns = ["x", "y"]

    def to_dict(self, orient):
        assert orient == "split"
        return {"columns": ["x", "y"], "data": [[1, 2], [3, 4]], "index": [0, 1]}


def test_table_from_a_dataframe():
    doc, _ = table_document(_FakeFrame())
    assert [c["name"] for c in doc["columns"]] == ["x", "y"]
    assert doc["data"] == [[1, 3], [2, 4]]


def test_table_row_cap_truncates():
    doc, total = table_document([{"i": i} for i in range(MAX_TABLE_ROWS + 5)])
    assert total == MAX_TABLE_ROWS + 5
    assert doc["rows"] == MAX_TABLE_ROWS and doc["truncated"] is True
    assert len(doc["data"][0]) == MAX_TABLE_ROWS


def test_table_rejects_other_input():
    with pytest.raises(TypeError):
        table_document("not a table")


def test_table_page_is_row_major_and_sortable():
    doc, _ = table_document([{"n": 3, "s": "c"}, {"n": 1, "s": "a"}, {"n": 2, "s": "b"}])
    page = table_page(doc, offset=1, limit=1)
    assert page["rows"] == [[1, "a"]] and page["total"] == 3 and page["offset"] == 1
    assert [c["name"] for c in page["columns"]] == ["n", "s"]
    ordered = table_page(doc, sort="n", order="desc")
    assert [r[0] for r in ordered["rows"]] == [3, 2, 1]
    with pytest.raises(ValueError):
        table_page(doc, sort="nope")


def test_table_page_sorts_missing_values_last():
    doc, _ = table_document([{"n": None}, {"n": 2}, {"n": 1}])
    assert [r[0] for r in table_page(doc, sort="n")["rows"]] == [1, 2, None]
    assert [r[0] for r in table_page(doc, sort="n", order="desc")["rows"]] == [2, 1, None]
