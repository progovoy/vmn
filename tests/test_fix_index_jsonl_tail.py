"""read_complete_lines: the one incremental JSONL reader (index and ui)."""
import pytest

from version_stamp.core.jsonl_tail import UnterminatedEntry, read_complete_lines


class _Files:
    def __init__(self, data):
        self.data = data

    def read_file_from(self, app_name, verstr, name, offset):
        return None if self.data is None else self.data[offset:]


def _read(data, offset=0, **kwargs):
    return read_complete_lines(_Files(data), "app", "v", "log.w.jsonl", offset, **kwargs)


def test_a_missing_file_reads_as_none():
    assert _read(None) is None


def test_complete_lines_are_parsed_and_consumed():
    data = b'{"a": 1}\n\nnot json\n{"b": 2}\n'
    assert _read(data) == ([{"a": 1}, {"b": 2}], len(data))


def test_reading_starts_at_the_offset():
    first = b'{"a": 1}\n'
    assert _read(first + b'{"b": 2}\n', offset=len(first)) == ([{"b": 2}], 9)


def test_a_half_written_line_is_left_for_the_next_read():
    assert _read(b'{"a": 1}\n{"b": ') == ([{"a": 1}], 9)


def test_a_whitespace_tail_is_consumed():
    assert _read(b'{"a": 1}\n  ') == ([{"a": 1}], 11)


def test_a_complete_unterminated_line_is_taken_by_default():
    assert _read(b'{"a": 1}\n{"b": 2}') == ([{"a": 1}, {"b": 2}], 17)


def test_a_complete_unterminated_line_raises_when_not_taken():
    with pytest.raises(UnterminatedEntry):
        _read(b'{"a": 1}\n{"b": 2}', take_unterminated=False)


def test_invalid_utf8_is_replaced_unless_strict():
    data = b'{"a": "\xff"}\n'
    assert _read(data) == ([{"a": "�"}], len(data))
    with pytest.raises(UnicodeDecodeError):
        _read(data, errors="strict")
