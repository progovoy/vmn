"""A record's file listing leaves out a symlink whose target is outside the
record dir (plan 42 E9b): what is not listed is never indexed or read by a
listing-driven reader (the run list, the log parse). A link inside the record
still lists. Only a symlink pays a realpath: a regular entry costs nothing more.
"""
import os

import pytest

from vmn_exp.storage import listing


@pytest.fixture
def record(tmp_path):
    path = tmp_path / "rec"
    (path / "log").mkdir(parents=True)
    (path / "run_state.yml").write_text("x: 1\n")
    (path / "log" / "w.jsonl").write_text("{}\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("db_password=hunter2\n")
    return path, outside


@pytest.mark.parametrize("scan", [listing.files_in, lambda p: listing.scan_dir(p)[0]],
                         ids=["files_in", "scan_dir"])
def test_record_listing_skips_symlinks_leaving_the_record_dir(record, scan):
    path, outside = record
    os.symlink(outside / "secret", path / "metadata.yml")
    os.symlink(outside / "secret", path / "log" / "x.jsonl")

    assert set(scan(str(path))) == {"run_state.yml", "log/w.jsonl"}


def test_a_log_folder_linked_out_of_the_record_is_not_listed(record):
    path, outside = record
    (outside / "a.jsonl").write_text("{}\n")
    os.rename(path / "log", path / "old_log")
    os.symlink(outside, path / "log")

    assert set(listing.files_in(str(path))) == {"run_state.yml"}


def test_record_listing_keeps_symlinks_inside_the_record_dir(record):
    path, _ = record
    os.symlink(path / "run_state.yml", path / "metadata.yml")
    os.symlink(path / "log" / "w.jsonl", path / "log" / "y.jsonl")

    assert set(listing.files_in(str(path))) == {
        "run_state.yml", "metadata.yml", "log/w.jsonl", "log/y.jsonl"}
