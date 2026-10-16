"""SearchRowsWriter writes only what moved since its last write (plan 25 F5):
a heartbeat-only generation re-sends the changed rows, not the app's all."""
from vmn_exp.ui.search_rows_writer import SearchRowsWriter


class _RecordingSql:
    def __init__(self):
        self.calls = []

    def write(self, workspace, app, entries, removed=None):
        self.calls.append(([verstr for verstr, _, _ in entries], removed))


class _Index:
    leading = True


class _Snapshot:
    def __init__(self, generation, rows):
        self.generation = generation
        self.rows = rows
        self.run_states = {}
        self.run_state_observed_at = {}

    def summarized(self, schema):
        return self


def _row(verstr, loss=1.0):
    return {"verstr": verstr, "metrics": {"loss": loss}}


def _writer():
    sql = _RecordingSql()
    writer = SearchRowsWriter(sql)
    index = _Index()
    writer.note(index, (0, "ws", "app", lambda: {}))
    return writer, sql, index


def test_first_write_is_a_full_sync():
    writer, sql, index = _writer()
    writer.refreshed(index, _Snapshot(1, [_row("a"), _row("b")]))
    assert sql.calls == [(["a", "b"], None)]


def test_a_new_generation_sends_only_the_changed_rows():
    writer, sql, index = _writer()
    writer.refreshed(index, _Snapshot(1, [_row("a"), _row("b")]))
    writer.refreshed(index, _Snapshot(2, [_row("a"), _row("b", loss=0.5)]))
    assert sql.calls[1:] == [(["b"], [])]


def test_an_unchanged_new_generation_writes_nothing():
    writer, sql, index = _writer()
    writer.refreshed(index, _Snapshot(1, [_row("a")]))
    writer.refreshed(index, _Snapshot(2, [_row("a")]))
    assert sql.calls[1:] == []


def test_removed_runs_are_deleted_by_name():
    writer, sql, index = _writer()
    writer.refreshed(index, _Snapshot(1, [_row("a"), _row("b")]))
    writer.refreshed(index, _Snapshot(2, [_row("b")]))
    # b moved to position 0: its row is re-sent with the new position.
    assert sql.calls[1:] == [(["b"], ["a"])]


def test_taking_the_lead_back_starts_with_a_full_sync():
    writer, sql, index = _writer()
    writer.refreshed(index, _Snapshot(1, [_row("a")]))
    index.leading = False
    writer.refreshed(index, _Snapshot(2, [_row("a")]))
    index.leading = True
    writer.refreshed(index, _Snapshot(3, [_row("a")]))
    assert sql.calls == [(["a"], None), (["a"], None)]
