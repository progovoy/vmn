"""``vmn-exp similar-backfill <app>``: give runs recorded without features
(before plan 18, or after a failed capture) the ``features`` entry their code
implies, under this host's writer id — and leave everything else alone."""
import pytest
from backfill_helpers import (
    BACKFILLER,
    COMMITS,
    CREATOR,
    FILES,
    as_backfiller,
    dirty_run,
    feature_writers,
    features_entries,
    seed_code,
    seed_run,
    set_state,
)
from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.cli import similar_backfill
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.index import indexed_snapshot

V1 = "0.0.2-dev.abc1234.1234567"
V2 = V1 + ".r2"
V3 = V1 + ".r3"


@pytest.fixture
def store(app_layout, monkeypatch):
    _bootstrap(app_layout)
    as_backfiller(monkeypatch)
    storage = _storage(app_layout)
    seed_code(storage, app_layout.app_name)
    return storage


def _backfill(app_layout, capfd, *args):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="similar-backfill", extra_args=list(args))
    return code, capfd.readouterr().out.splitlines()


def test_a_dirty_run_gets_its_codes_files_symbols_commits_and_author(app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1)

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  backfilled (2 files, 2 symbols, 1 commit)" in lines
    assert lines[-1] == "backfilled 1, partial 0, skipped 0, failed 0"
    [entry] = features_entries(store, app, V1)
    assert entry["features_version"] == FEATURES_VERSION and entry["source"] == "backfill"
    assert sorted(entry["changed"]["files"]) == FILES
    assert {"src/loss.py::focal_loss", "src/train.py::train_step"} <= set(
        entry["changed"]["symbols"])
    assert entry["commits"] == COMMITS
    assert entry["author"] == {"git_user_email": "alice@x.io", "source": "commit",
                               "writer": CREATOR}
    assert feature_writers(store, app, V1) == [BACKFILLER]
    assert indexed_snapshot(store, app, wait=True).features_of(V1)["commits"] == COMMITS


def test_a_second_backfill_skips_every_run(app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1)
    newer = {"timestamp": "2026-01-01T00:00:02Z", "type": "features",
             "features_version": FEATURES_VERSION + 1, "source": "capture"}
    dirty_run(store, app, V2, log=[newer])
    assert _backfill(app_layout, capfd)[0] == 0

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  skipped (up to date)" in lines and f"{V2}  skipped (up to date)" in lines
    assert lines[-1] == "backfilled 0, partial 0, skipped 2, failed 0"
    assert len(features_entries(store, app, V1)) == 1
    assert [e["features_version"] for e in features_entries(store, app, V2)] == \
        [FEATURES_VERSION + 1]


def test_live_runs_and_imports_are_skipped_created_and_failed_runs_are_not(
        app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1, state="running", exit_code=None)
    dirty_run(store, app, V2, state=None)
    stuck = dirty_run(store, app, V3, state=None)
    set_state(store, app, stuck, "running", age_sec=3600)
    failed = dirty_run(store, app, V1 + ".r4", exit_code=1)
    imported = seed_run(store, app, "0.0.2-dev.mlflow.r1",
                        imported_from={"tool": "mlflow", "run_id": "abc"})

    code, lines = _backfill(app_layout, capfd)

    assert code == 0
    assert f"{V1}  skipped (running)" in lines
    assert f"{stuck}  skipped (stuck)" in lines
    assert f"{imported}  skipped (imported)" in lines
    assert lines[-1] == "backfilled 2, partial 0, skipped 3, failed 0"
    assert [bool(features_entries(store, app, v)) for v in (V1, V2, stuck, failed, imported)] \
        == [False, True, False, True, False]


def test_dry_run_reports_what_it_would_write_and_writes_nothing(app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1)

    code, lines = _backfill(app_layout, capfd, "--dry-run")

    assert code == 0
    assert f"{V1}  backfilled (2 files, 2 symbols, 1 commit)" in lines
    assert lines[-1] == "backfilled 1, partial 0, skipped 0, failed 0 (dry run: nothing written)"
    assert features_entries(store, app, V1) == []
    assert _backfill(app_layout, capfd)[1][-1] == "backfilled 1, partial 0, skipped 0, failed 0"


def test_an_older_entry_keeps_its_author_and_untracked_files(app_layout, store, capfd):
    app = app_layout.app_name
    author = {"git_user_email": "bob@x.io", "os_user": "bob", "writer": "laptop",
              "source": "git"}
    older = {"timestamp": "2026-01-01T00:00:02Z", "type": "features",
             "features_version": FEATURES_VERSION - 1, "source": "capture",
             "author": author, "commits": ["old subject"], "truncated": True,
             "changed": {"files": ["old.py"], "symbols": ["old.py::f"],
                         "untracked": ["notes/idea.md"]}}
    dirty_run(store, app, V1, log=[older])

    assert _backfill(app_layout, capfd)[0] == 0

    entry = indexed_snapshot(store, app, wait=True).features_of(V1)
    assert entry["features_version"] == FEATURES_VERSION and entry["source"] == "backfill"
    assert entry["author"] == author
    assert sorted(entry["changed"]["files"]) == FILES
    assert entry["changed"]["untracked"] == ["notes/idea.md"]
    assert entry["commits"] == COMMITS and "truncated" not in entry


def test_a_failing_run_is_reported_the_rest_still_backfilled(
        app_layout, store, capfd, monkeypatch):
    app = app_layout.app_name
    seed_run(store, app, V1)
    dirty_run(store, app, V2)
    real = similar_backfill.code_patch_texts

    def flaky(storage, app_name, key, dep_paths=()):
        raise OSError("bucket on fire")

    monkeypatch.setattr(similar_backfill, "code_patch_texts", flaky)
    code, lines = _backfill(app_layout, capfd)
    monkeypatch.setattr(similar_backfill, "code_patch_texts", real)

    assert code == 1
    assert f"{V2}  failed (bucket on fire)" in lines
    assert f"{V1}  backfilled (clean tree)" in lines
    assert lines[-1] == "backfilled 1, partial 0, skipped 0, failed 1"
    assert features_entries(store, app, V2) == []


def test_all_apps_backfills_every_app_of_the_store(app_layout, store, capfd):
    app = app_layout.app_name
    dirty_run(store, app, V1)
    seed_code(store, "other_app")
    dirty_run(store, "other_app", V1)

    code, lines = _backfill(app_layout, capfd, "--all-apps")

    assert code == 0
    assert lines.index("other_app:") < lines.index(f"{app}:")
    assert lines[-1] == "backfilled 2, partial 0, skipped 0, failed 0"
    assert features_entries(store, "other_app", V1)[0]["changed"]["files"]


def test_similar_backfill_is_a_writing_action():
    from vmn_exp.cli.experiment import READ_ONLY_ACTIONS
    from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS

    assert "similar-backfill" in EXPERIMENT_ACTIONS
    assert "similar-backfill" not in READ_ONLY_ACTIONS


def test_runs_sharing_a_code_object_read_and_parse_it_once(
        app_layout, store, capfd, monkeypatch):
    app = app_layout.app_name
    dirty_run(store, app, V1)
    dirty_run(store, app, V2)
    calls = []
    real = similar_backfill.features_from_patches
    monkeypatch.setattr(similar_backfill, "features_from_patches",
                        lambda texts: calls.append(1) or real(texts))

    assert _backfill(app_layout, capfd)[0] == 0

    assert len(calls) == 1
    assert features_entries(store, app, V1)[0]["changed"] == \
        features_entries(store, app, V2)[0]["changed"]
