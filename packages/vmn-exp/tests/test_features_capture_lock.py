"""``start_run()`` in a checkout captures the run's features — git config
reads, patch parsing — before it takes the repo lock, which it holds only to
claim the verstr; the features entry still follows the create entry."""
import contextlib
import os

from exp_helpers import _bootstrap, _storage
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.gitmode import checkout
from vmn_exp.sdk import start_run


def test_start_run_captures_features_before_taking_the_repo_lock(app_layout, monkeypatch):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "data.py", "rows = 1\n")
    with open(os.path.join(app_layout.repo_path, "data.py"), "w") as f:
        f.write("rows = 2\n")
    held, captures = [], []
    real_lock, real_capture = checkout.get_repo_lock, checkout.capture_features

    @contextlib.contextmanager
    def lock(root):
        with real_lock(root):
            held.append(root)
            try:
                yield
            finally:
                held.pop()

    def capture(vcs, captured):
        captures.append(bool(held))
        return real_capture(vcs, captured)

    monkeypatch.setattr(checkout, "get_repo_lock", lock)
    monkeypatch.setattr(checkout, "capture_features", capture)
    with start_run(app_layout.app_name, system_metrics=False, capture_env=False) as run:
        verstr = run.id

    assert captures == [False]
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    assert [e["type"] for e in log][:2] == ["create", "features"]
    assert fold_features(fold_log(log))["changed"]["files"] == ["data.py"]
