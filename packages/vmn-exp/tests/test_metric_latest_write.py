"""A metric's "latest" value is its last write, never the value at its
highest step: a resumed writer that restarts its step counter keeps the
newest value (plan 32 §0)."""
from vmn_exp.core.fold import fold_metrics, new_fold
from vmn_exp.core.fold_blocks import apply_header, footer_entries
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import MetricIndexReader, build_index

# Steps 0..120 (value 0.954 at step 120), then a resumed writer from step 0
# whose last write is 0.989 at step 5.
STEPS = list(range(121)) + list(range(6))
VALUES = [0.5] * 120 + [0.954] + [0.98] * 5 + [0.989]
TS = [1_000_000 * (i + 1) for i in range(len(STEPS))]


def _footer(cols):
    data = build_index("w", {"best": cols})
    return MetricIndexReader(lambda off, n: data[off:off + n], len(data)).footer


def test_a_vmx_footer_keeps_the_first_and_last_write_not_the_step_ends():
    summary = _footer(Columns(STEPS, TS, VALUES))["keys"]["best"]["summary"]
    assert summary["last"] == [0.989, 5, TS[-1]]
    assert summary["first"] == [0.5, 0, TS[0]]


def test_the_index_fold_of_a_vmx_takes_the_last_write():
    footer = _footer(Columns(STEPS, TS, VALUES))
    fold = apply_header(new_fold(), "w", 0, {"keys": footer_entries(footer)})
    metrics, summary, _ = fold_metrics(fold)
    assert metrics["best"] == 0.989
    assert summary["best"]["last"] == 0.989
