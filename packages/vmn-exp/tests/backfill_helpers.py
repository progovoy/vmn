"""Runs recorded without features (before plan 18, or a failed capture), for
the ``vmn-exp similar-backfill`` tests: records seeded straight into a store."""
import datetime
import os

import yaml
from version_stamp.snapshot.record import patch_summary
from vmn_exp.core import writer
from vmn_exp.core.code_store import store_code
from vmn_exp.core.status import RUN_STATE_FILE

CODE = "0.0.2-dev.abc1234.1234567"
KEY = CODE + ".1234567ffff"
CREATOR = "gpu-07"
BACKFILLER = "backfiller"
WT = """diff --git a/src/loss.py b/src/loss.py
index 1111111..2222222 100644
--- a/src/loss.py
+++ b/src/loss.py
@@ -10,3 +10,4 @@ def focal_loss(logits, target):
     gamma = 2
+    alpha = 0.25
     return gamma
"""
LC = """From 0123456789abcdef0123456789abcdef01234567 Mon Sep 17 00:00:00 2001
From: Alice Example <alice@x.io>
Date: Thu, 1 Jan 2026 00:00:00 +0000
Subject: [PATCH] try focal loss

---
 src/train.py | 1 +
 1 file changed, 1 insertion(+)

diff --git a/src/train.py b/src/train.py
index 3333333..4444444 100644
--- a/src/train.py
+++ b/src/train.py
@@ -1,2 +1,3 @@ def train_step(batch):
     loss = 1
+    loss = 2
--
2.40.0
"""
PAYLOAD = {"working_tree": WT, "local_commits": LC, "untracked_files": b"\x1f\x8bTAR"}
FILES = ["src/loss.py", "src/train.py"]
COMMITS = ["try focal loss"]


def as_backfiller(monkeypatch, writer_id=BACKFILLER):
    """Make *writer_id* this process's writer id (a host's)."""
    monkeypatch.setenv("VMN_WRITER_ID", writer_id)
    writer._WRITER_ID = None


def seed_code(storage, app, key=KEY, payload=None):
    payload = PAYLOAD if payload is None else payload
    store_code(storage, app, key, payload, patch_summary(payload))


def seed_run(storage, app, verstr, state="finished", exit_code=0, log=(), **meta):
    """A run of *app* whose create entry *CREATOR* wrote; *state* None = created."""
    metadata = dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z",
                     "base_version": "0.0.2", "base_commit": "abc1234",
                     "code_verstr": CODE}, **meta)
    storage.save(app, verstr, metadata, {})
    storage.append_log_entry(app, verstr, CREATOR, {
        "timestamp": "2026-01-01T00:00:01Z", "type": "create", "note": None})
    for entry in log:
        storage.append_log_entry(app, verstr, CREATOR, entry)
    if state:
        set_state(storage, app, verstr, state, exit_code)
    return verstr


def dirty_run(storage, app, verstr, **meta):
    """A run of a dirty tree, its code in the code object *KEY*."""
    return seed_run(storage, app, verstr, diff_hash="1234567ffff", code=KEY,
                    dirty_states=["pending", "outgoing"], **meta)


def set_state(storage, app, verstr, state, exit_code=None, age_sec=0):
    beat = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_sec)
    stamp = beat.strftime("%Y-%m-%dT%H:%M:%SZ")
    storage.save_file(app, verstr, RUN_STATE_FILE, yaml.dump({
        "state": state, "pid": 1, "host": "h", "started_at": stamp, "heartbeat": stamp,
        "heartbeat_interval_sec": 30, "exit_code": exit_code}, sort_keys=False))
    if age_sec:
        path = os.path.join(storage.local_record_dir(app, verstr), RUN_STATE_FILE)
        os.utime(path, (beat.timestamp(), beat.timestamp()))


def features_entries(storage, app, verstr):
    return [e for e in storage.load_merged_log(app, verstr) if e.get("type") == "features"]


def feature_writers(storage, app, verstr):
    """The writers whose logs hold a ``features`` entry."""
    return sorted(w for w, entries in storage.load_logs_by_writer(app, verstr).items()
                  if any(e.get("type") == "features" for e in entries))
