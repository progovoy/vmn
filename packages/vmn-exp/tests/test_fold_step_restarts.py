"""The fold marks a metric whose last write is below its highest step (its
steps went back without a rewind and stayed below): index rows carry
``step_restarts`` (``{metric: {"from": highest, "to": last step}}``, absent
when none), from any source, whatever order the chunks fold in."""
from vmn_exp.core.fold import fold_log, fold_row, new_fold
from vmn_exp.core.fold_blocks import apply_header, apply_sums, footer_entries
from vmn_exp.core.fold_sums import add_block
from vmn_exp.core.metric_block import decode_blocks, encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import MetricIndexReader, build_index
from vmn_exp.core.metric_time import us_to_iso

T0 = 1_700_000_000_000_001  # not a whole second: its ISO form has digits


def _restarts(fold):
    return fold_row(1, {"verstr": "v"}, fold).get("step_restarts")


def _entry(i, step, value=0.5, name="best"):
    entry = {"timestamp": us_to_iso(T0 + i), "type": "metrics", "values": {name: value}}
    if step is not None:
        entry["step"] = step
    return entry


def _header(steps, t0, name="best"):
    """A block header of *steps* written one microsecond apart from *t0*."""
    cols = Columns(steps, [T0 + t0 + i for i in range(len(steps))], [0.5] * len(steps))
    return next(decode_blocks(encode_block({name: cols}))).header


def test_a_logged_restart_is_on_the_row():
    fold = fold_log([_entry(i, i) for i in range(121)] + [_entry(200 + i, i) for i in range(3)])
    assert _restarts(fold) == {"best": {"from": 120, "to": 2}}


def test_monotone_and_step_less_metrics_carry_none():
    fold = fold_log([_entry(i, i) for i in range(5)] + [_entry(10 + i, None, name="cpu")
                                                       for i in range(3)])
    assert _restarts(fold) is None


def test_a_rewind_is_not_a_restart():
    log = [_entry(i, i) for i in range(10)]
    log.append({"timestamp": us_to_iso(T0 + 20), "type": "rewind", "step": 4})
    log += [_entry(30 + i, 5 + i) for i in range(3)]
    assert _restarts(fold_log(log)) is None


def test_a_block_header_carries_the_restart_inside_it():
    header = _header([0, 1, 2, 0, 1], 0)
    assert header["order"] == "write"
    assert header["keys"][0]["r"] == [2, 1]
    assert "r" not in _header([0, 1, 2], 0)["keys"][0]
    assert _restarts(apply_header(new_fold(), "w", 0, header)) == {"best": {"from": 2, "to": 1}}


def test_blocks_restarting_across_each_other_in_either_fold_order():
    first, second = _header(list(range(10)), 0), _header([3, 4, 5], 100)
    for order in ((first, second), (second, first)):
        fold = new_fold()
        for base, header in zip((0, 10), order):
            apply_header(fold, "w", base, header)
        assert _restarts(fold) == {"best": {"from": 9, "to": 5}}


def test_a_writer_continuing_another_is_no_restart_in_either_order():
    a, b = _header(list(range(10)), 0), _header(list(range(10, 20)), 100)
    for (wa, ha), (wb, hb) in (((("a", a)), ("b", b)), (("b", b), ("a", a))):
        fold = new_fold()
        apply_header(fold, wa, 0, ha)
        apply_header(fold, wb, 0, hb)
        assert _restarts(fold) is None


def test_writers_taking_turns_with_rising_steps_are_no_restart():
    # Two clones of one run take turns: a at steps 1-2, b at 11-12, a at 21-22.
    a1, b, a2 = _header([1, 2], 1), _header([11, 12], 11), _header([21, 22], 21)
    for order in (("a", a1), ("a", a2), ("b", b)), (("b", b), ("a", a2), ("a", a1)):
        fold = new_fold()
        for base, (writer, header) in enumerate(order):
            apply_header(fold, writer, base * 2, header)
        assert _restarts(fold) is None


def test_a_writer_resuming_after_another_with_lower_steps_restarts():
    first, resumed = _header(list(range(10)), 0), _header([0, 1, 2], 100)
    for order in (("a", first), ("b", resumed)), (("b", resumed), ("a", first)):
        fold = new_fold()
        for writer, header in order:
            apply_header(fold, writer, 0, header)
        assert _restarts(fold) == {"best": {"from": 9, "to": 2}}


def test_a_vmx_footer_folds_its_restart_point():
    steps = list(range(121)) + list(range(6))
    data = build_index("w", {"best": Columns(steps, [T0 + i for i in range(len(steps))],
                                             [0.5] * len(steps))})
    footer = MetricIndexReader(lambda off, n: data[off:off + n], len(data)).footer
    fold = apply_header(new_fold(), "w", 0, {"keys": footer_entries(footer)})
    assert _restarts(fold) == {"best": {"from": 120, "to": 5}}


def test_a_writers_sums_keep_its_restart():
    sums = {}
    add_block(sums, 0, _header(list(range(10)), 0))
    add_block(sums, 10, _header([3, 4], 100))
    assert _restarts(apply_sums(new_fold(), "w", sums)) == {"best": {"from": 9, "to": 4}}
    inside = {}
    add_block(inside, 0, _header([0, 5, 1], 0))
    assert _restarts(apply_sums(new_fold(), "w", inside)) == {"best": {"from": 5, "to": 1}}
