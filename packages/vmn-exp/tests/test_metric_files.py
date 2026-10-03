"""Names of a record's metric objects (plan 12 §4.2): streams
``metrics/<w>.vms`` + segments ``metrics/<w>@<seq>.vms``, indexed
``metrics/<w>.vmx`` superseding them."""
from vmn_exp.core.metric_files import (
    group_metric_names,
    indexed_name,
    is_metric_file,
    stream_name,
    stream_writer_and_seq,
)


def test_stream_and_segment_names_follow_the_log_seq_scheme():
    assert stream_name("w") == "metrics/w.vms"
    assert stream_name("w", 3) == "metrics/w@000003.vms"
    assert indexed_name("w") == "metrics/w.vmx"
    assert stream_writer_and_seq("metrics/w@000003.vms") == ("w", 3)
    assert stream_writer_and_seq("metrics/w.vms") == ("w", 0)


def test_only_metric_objects_are_metric_files():
    assert is_metric_file("metrics/w.vms")
    assert is_metric_file("metrics/w.vmx")
    assert not is_metric_file("log/w.jsonl")
    assert not is_metric_file("metrics/sub/w.vms")
    assert not is_metric_file("metrics/w.txt")


def test_grouping_orders_a_writers_segments():
    names = ["metrics/a@000002.vms", "metrics/a.vms", "metrics/a@000001.vms",
             "metrics/b.vms", "log/a.jsonl"]
    assert group_metric_names(names) == {
        "a": ["metrics/a.vms", "metrics/a@000001.vms", "metrics/a@000002.vms"],
        "b": ["metrics/b.vms"],
    }


def test_an_indexed_file_supersedes_its_writers_streams():
    names = ["metrics/a.vms", "metrics/a@000001.vms", "metrics/a.vmx", "metrics/b.vms"]
    assert group_metric_names(names) == {"a": ["metrics/a.vmx"], "b": ["metrics/b.vms"]}


def test_sealed_parts_are_named_per_writer_and_are_not_the_final_index():
    from vmn_exp.core.metric_files import is_indexed_file, is_part_file, part_name

    assert part_name("w", 2) == "metrics/w@p000002.vmx"
    assert is_part_file("metrics/w@p000002.vmx")
    assert is_metric_file("metrics/w@p000002.vmx")
    assert not is_indexed_file("metrics/w@p000002.vmx")
    assert not is_part_file("metrics/w.vmx")


def test_parts_come_first_then_the_streams_written_after_them():
    names = ["metrics/a.vms", "metrics/a@p000002.vmx", "metrics/a@p000001.vmx"]
    assert group_metric_names(names) == {
        "a": ["metrics/a@p000001.vmx", "metrics/a@p000002.vmx", "metrics/a.vms"]}


def test_the_final_index_supersedes_parts_too():
    names = ["metrics/a.vms", "metrics/a@p000001.vmx", "metrics/a.vmx"]
    assert group_metric_names(names) == {"a": ["metrics/a.vmx"]}
