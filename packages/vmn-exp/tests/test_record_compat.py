"""The SDK/server compatibility contract (docs/packaging.md, Compatibility):
a reader reads the records any older SDK wrote in the same store layout and
record format. Each format this reader accepts keeps one golden record, frozen
as the SDK that last wrote it laid it out, under ``golden/record_format_<N>/``
(plan 43 F11)."""
import os

from empty_storage import EmptyStorage
from vmn_exp.core.fold import fold_log
from vmn_exp.core.log import experiment_row, load_log
from vmn_exp.core.logfiles import group_log_names, parse_jsonl
from vmn_exp.core.metric_files import group_metric_objects
from vmn_exp.core.record_format import RECORD_FORMAT_VERSION
from vmn_exp.core.status import SUCCEEDED, load_run_state, status_fields
from vmn_exp.storage.files import merged_log

GOLDEN = os.path.join(os.path.dirname(__file__), "golden")
# Format 1 is refused with the migrate hint (test_record_format_read.py).
FIRST_READABLE_FORMAT = 2
APP = "golden"
# Written by vmn-exp-sdk 0.1.37, git-free (VMN_SNAPSHOT_METADATA), writer trainer-0.
FORMAT_2_VERSTR = "0.0.1-dev.1+aaaaaaaa.trainer-0"


class GoldenStorage(EmptyStorage):
    """One record's files, as read from a golden directory: a store holding
    only that record, with no store of its own behind it."""

    def __init__(self, verstr, files):
        self._verstr, self._files = verstr, files

    def load_file(self, app_name, verstr, filename):
        return self._files.get(filename) if verstr == self._verstr else None

    def load_record(self, app_name, verstr):
        metadata = self.load_metadata(app_name, verstr)
        return (metadata, {}) if metadata else (None, None)

    def metric_objects(self, app_name, verstr):
        return group_metric_objects(
            {name: len(data) for name, data in self._files.items()
             if name.startswith("metrics/")})

    def load_merged_log(self, app_name, verstr):
        logs = {
            writer: [entry for name in names
                     for entry in parse_jsonl(self._files[name].decode(), writer)]
            for writer, names in group_log_names(self._files).items()
        }
        return merged_log(self, app_name, verstr, logs)


def _read_tree(root):
    files = {}
    for folder, _, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                files[os.path.relpath(path, root).replace(os.sep, "/")] = f.read()
    return files


def _golden_storage(record_format, verstr):
    return GoldenStorage(verstr, _read_tree(
        os.path.join(GOLDEN, f"record_format_{record_format}")))


def test_a_format_2_record_written_by_0_1_37_folds_to_the_same_metrics_params_and_status():
    storage = _golden_storage(2, FORMAT_2_VERSTR)
    meta = storage.load_metadata(APP, FORMAT_2_VERSTR)
    assert meta["format_version"] == 2

    row = experiment_row(1, meta, load_log(storage, APP, FORMAT_2_VERSTR))
    state = load_run_state(storage, APP, FORMAT_2_VERSTR)

    assert row["params"] == {"lr": 0.05, "layers": 3, "optimizer": "adam", "batch": 32}
    assert row["metrics"] == {
        "loss": 0.5, "epoch": 2, "val_loss": 0.4, "accuracy": 0.9,
        "lr": 0.05, "layers": 3, "batch": 32,
    }
    assert row["tags"] == {"team": "vision", "stage": "eval"}
    assert row["name"] == "golden-run"
    assert status_fields(state)["status"] == SUCCEEDED


def test_a_log_line_of_an_unknown_type_adds_nothing_to_the_fold():
    log = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "create", "params": {"lr": 0.1}},
        {"timestamp": "2026-01-01T00:00:01Z", "type": "metrics", "step": 0,
         "values": {"loss": 1.0}},
        {"timestamp": "2026-01-01T00:00:02Z", "type": "tags", "set": {"team": "a"}},
    ]
    unknown = {
        "timestamp": "2026-01-01T00:00:03Z", "type": "from_a_newer_sdk", "step": 1,
        "values": {"loss": 0.1}, "set": {"team": "b"}, "name": "x", "text": "y",
        "path": "artifacts/z", "uri": "s3://b/z",
    }

    assert fold_log(log + [unknown]) == fold_log(log)


def test_every_record_format_this_reader_accepts_has_a_golden_record():
    accepted = {f"record_format_{n}"
                for n in range(FIRST_READABLE_FORMAT, RECORD_FORMAT_VERSION + 1)}
    goldens = {name for name in os.listdir(GOLDEN) if name.startswith("record_format_")}
    assert goldens == accepted
