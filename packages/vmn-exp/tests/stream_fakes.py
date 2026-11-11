"""A storage fake that records which stream each write names, for the
adoption tests (plan 38 A5): every writer of a record copy gets the copy's
one owner, as a shared local copy answers."""
from empty_storage import EmptyStorage

from vmn_exp.core.status import RUN_STATE_FILE

APP, V = "app", "1.0.0-dev.abc.r1"


class StreamRecorder(EmptyStorage):
    """Holds nothing; remembers the stream of every append and sync, the
    writers it was asked an owner for, and every run-state save."""

    def __init__(self, owner="o1"):
        self.owner = owner
        self.owner_asked = []
        self.metric_blocks = []
        self.log_entries = []
        self.synced = []
        self.state_saves = []

    def stream_owner(self, app_name, verstr, writer):
        self.owner_asked.append(writer)
        return self.owner

    def append_metric_block(self, app_name, verstr, writer_id, data):
        self.metric_blocks.append(writer_id)
        return True

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        self.log_entries.extend((writer_id, e) for e in entries)
        return True

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        return self.append_log_entries(app_name, verstr, writer_id, [entry])

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        self.synced.append(("log", writer_id))

    def sync_metrics_to_remote(self, app_name, verstr, writer_id):
        self.synced.append(("metrics", writer_id))

    def save_file(self, app_name, verstr, filename, data):
        if filename == RUN_STATE_FILE:
            self.state_saves.append(data)

    def entries_of(self, entry_type):
        return [(stream, e) for stream, e in self.log_entries if e.get("type") == entry_type]
