"""A pure ``DERIVED_VERSION`` bump keeps the derived rows it re-derives: while
the derive rewrites them, the index serves them ``loading`` (plan 33 §2.3,
§4), never an empty board."""
from test_fix_index_refresh_scale import clock, live_store  # noqa: F401  (fixtures)
from test_index_upgrade_kept_io import held, serves_kept_rows_mid_derive, upgraded  # noqa: F401
from test_ui_index_migrating import _older_derived
from vmn_exp.core import index_derive
from vmn_exp.core.index import ExperimentIndex


def test_a_derived_bump_serves_the_kept_rows_loading_while_it_rederives(
        live_store, clock, tmp_path, held, monkeypatch):
    monkeypatch.setattr(ExperimentIndex, "use_io_process", lambda self: False)
    hold, release = held
    hold(index_derive, "derive_chunk")
    index, want = upgraded(live_store, str(tmp_path / "idx.sqlite"), False, _older_derived)
    try:
        serves_kept_rows_mid_derive(index, want, release)
    finally:
        index.close()
