"""Shared file helpers in version_stamp.core.utils."""
import os
import stat

import pytest

from version_stamp.core.utils import (
    MalformedBlockError,
    atomic_write,
    marked_block_span,
    upsert_marked_block,
)

BEGIN = "<!-- BEGIN x -->"
END = "<!-- END x -->"
BLOCK = f"{BEGIN}\nnew\n{END}"


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.parametrize("umask", [0o022, 0o077])
def test_atomic_write_new_file_gets_umask_shaped_mode(tmp_path, umask):
    old = os.umask(umask)
    try:
        atomic_write(str(tmp_path / "f"), "data")
    finally:
        os.umask(old)
    assert _mode(tmp_path / "f") == 0o666 & ~umask


def test_atomic_write_preserves_existing_mode(tmp_path):
    target = tmp_path / "f"
    target.write_text("old")
    os.chmod(target, 0o640)
    atomic_write(str(target), "new")
    assert target.read_text() == "new"
    assert _mode(target) == 0o640


def test_atomic_write_accepts_bytes_and_leaves_no_temp_files(tmp_path):
    atomic_write(str(tmp_path / "f"), b"\x00\x01")
    assert (tmp_path / "f").read_bytes() == b"\x00\x01"
    assert os.listdir(tmp_path) == ["f"]


def test_atomic_write_failure_keeps_old_file_and_cleans_temp(tmp_path):
    target = tmp_path / "f"
    target.write_text("old")
    with pytest.raises(TypeError):
        atomic_write(str(target), 123)
    assert target.read_text() == "old"
    assert os.listdir(tmp_path) == ["f"]


def test_marked_block_span_absent_and_present():
    assert marked_block_span("plain\n", BEGIN, END) is None
    content = f"a\n{BEGIN}\nold\n{END}\nb\n"
    start, stop = marked_block_span(content, BEGIN, END)
    assert content[start:stop] == f"{BEGIN}\nold\n{END}"


@pytest.mark.parametrize(
    "content",
    [
        f"{BEGIN}\n",
        f"{END}\n",
        f"{END}\n{BEGIN}\n",
        f"{BEGIN}\n{END}\n{BEGIN}\n{END}\n",
    ],
)
def test_marked_block_span_rejects_malformed(content):
    with pytest.raises(MalformedBlockError):
        marked_block_span(content, BEGIN, END)


def test_upsert_marked_block_replaces_in_place():
    content = f"a\n{BEGIN}\nold\n{END}\nb\n"
    assert upsert_marked_block(content, BEGIN, END, BLOCK) == (
        f"a\n{BLOCK}\nb\n",
        "Updated",
    )


def test_upsert_marked_block_appends_after_blank_line():
    assert upsert_marked_block("a\n\n\n", BEGIN, END, BLOCK) == (
        f"a\n\n{BLOCK}\n",
        "Appended",
    )


def test_upsert_marked_block_into_empty_content():
    assert upsert_marked_block(" \n", BEGIN, END, BLOCK) == (f"{BLOCK}\n", "Wrote")


def test_upsert_marked_block_rejects_malformed():
    with pytest.raises(MalformedBlockError):
        upsert_marked_block(f"{END}\n{BEGIN}\n", BEGIN, END, BLOCK)
