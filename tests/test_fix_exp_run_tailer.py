"""`vmn exp run` metrics-file tailing must be byte-exact and never raise.

The tailer used to count *characters* but seek by *bytes*, so the first
non-ASCII metrics line made the next poll land mid-character and raise
UnicodeDecodeError, killing the supervisor while the child ran on unsupervised.
"""

from version_stamp.cli.experiment import _MetricsTailer


def _append(path, data):
    with open(path, "ab") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def test_line_after_a_non_ascii_line_is_read_without_error(tmp_path):
    path = str(tmp_path / "metrics")
    tailer = _MetricsTailer(path)

    _append(path, "tag=éé\n")
    assert tailer.poll() == [(None, {"tag": "éé"})]

    _append(path, "loss=0.4\n")
    assert tailer.poll() == [(None, {"loss": 0.4})]


def test_many_non_ascii_lines_neither_drift_nor_duplicate(tmp_path):
    path = str(tmp_path / "metrics")
    tailer = _MetricsTailer(path)
    seen = []
    for i in range(6):
        _append(path, f"step={i} loss=0.{i} tag=日本\n")
        seen += tailer.poll()

    assert [step for step, _ in seen] == list(range(6))
    assert [values["loss"] for _, values in seen] == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]


def test_multibyte_character_split_across_polls_is_reassembled(tmp_path):
    path = str(tmp_path / "metrics")
    tailer = _MetricsTailer(path)

    _append(path, b"tag=\xc3")  # first byte of 'é', no newline yet
    assert tailer.poll() == []
    _append(path, b"\xa9 loss=0.5\n")

    assert tailer.poll() == [(None, {"tag": "é", "loss": 0.5})]


def test_invalid_utf8_bytes_never_raise(tmp_path):
    path = str(tmp_path / "metrics")
    tailer = _MetricsTailer(path)

    _append(path, b"loss=0.1 junk=\xff\xfe\n")
    records = tailer.poll()

    assert records[0][1]["loss"] == 0.1
    _append(path, "loss=0.2\n")
    assert tailer.poll() == [(None, {"loss": 0.2})]


def test_partial_trailing_line_waits_for_its_newline(tmp_path):
    path = str(tmp_path / "metrics")
    tailer = _MetricsTailer(path)

    _append(path, "loss=0.1\nloss=0.")
    assert tailer.poll() == [(None, {"loss": 0.1})]
    _append(path, "2\n")
    assert tailer.poll() == [(None, {"loss": 0.2})]


def test_missing_file_yields_nothing(tmp_path):
    assert _MetricsTailer(str(tmp_path / "absent")).poll() == []
