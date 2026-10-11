"""``vmn-exp similar`` with a text query (``--context``/``--context-file``,
``--text-only``), across every app of the store (``--all-apps``), with conf
weights, and git-free (``VMN_SNAPSHOT_METADATA``)."""
import io
import json

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _init_app, _run_vmn_init, _stamp_app, _storage
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.snapshot import open_storage


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_SNAPSHOT_METADATA", "VMN_EXPERIMENT_STORE",
                "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)


def _similar(app_layout, capfd, *args):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="similar", extra_args=list(args))
    return code, capfd.readouterr()


def _verstrs(app_layout, capfd, *args):
    code, out = _similar(app_layout, capfd, "--json", *args)
    assert code == 0, out.err
    return [item["verstr"] for item in json.loads(out.out)]


def _intents(storage, app):
    """a: focal loss, b: label smoothing, c (the target): focal loss again."""
    a = seed(storage, app, verstr(1), intent={"text": "focal loss for class imbalance"})
    b = seed(storage, app, verstr(2), intent={"text": "label smoothing"})
    c = seed(storage, app, verstr(3), intent={"text": "focal loss tuned"})
    return a, b, c


@pytest.fixture
def texts(app_layout):
    _bootstrap(app_layout)
    return _intents(_storage(app_layout), app_layout.app_name)


def test_context_replaces_the_target_runs_text(app_layout, capfd, texts):
    a, b, c = texts
    assert _verstrs(app_layout, capfd, "-v", c)[0] == a
    assert _verstrs(app_layout, capfd, "-v", c, "--context", "label smoothing")[0] == b


def test_text_only_is_a_pure_text_query_that_needs_no_working_tree(
        app_layout, capfd, texts, monkeypatch):
    from vmn_exp.gitmode import capture

    monkeypatch.setattr(capture, "capture_snapshot", _boom)
    code, out = _similar(app_layout, capfd, "--json", "--context", "label smoothing",
                         "--text-only")
    assert code == 0, out.err
    [item] = json.loads(out.out)
    assert item["verstr"] == texts[1] and set(item["signals"]) == {"text"}


def test_text_only_needs_a_context(app_layout, capfd, texts):
    code, out = _similar(app_layout, capfd, "--text-only")
    assert code == 1 and "--text-only" in out.err


def test_a_context_file_adds_its_front_matter_keywords_not_its_other_keys(
        app_layout, capfd, texts, tmp_path):
    noise = seed(_storage(app_layout), app_layout.app_name, verstr(4),
                 intent={"text": "keywords generator claude"})
    path = tmp_path / "intent.md"
    path.write_text("---\nkeywords: [label smoothing]\ngenerator: claude\n---\n"
                    "regularise the outputs\n")
    found = _verstrs(app_layout, capfd, "--context-file", str(path), "--text-only")
    assert found == [texts[1]] and noise not in found


def test_a_context_file_dash_reads_stdin(app_layout, capfd, texts, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("label smoothing\n"))
    assert _verstrs(app_layout, capfd, "-v", texts[2], "--context-file", "-")[0] == texts[1]


def test_an_unreadable_context_file_is_an_error(app_layout, capfd, texts, tmp_path):
    code, out = _similar(app_layout, capfd, "--context-file", str(tmp_path / "nope.md"),
                         "--text-only")
    assert code == 1 and "nope.md" in out.err


def test_a_failing_working_tree_capture_is_a_clear_error(app_layout, capfd, monkeypatch):
    from vmn_exp.gitmode import capture

    _bootstrap(app_layout)
    monkeypatch.setattr(capture, "capture_snapshot", _boom)
    code, out = _similar(app_layout, capfd)
    assert code == 1
    assert "working tree" in out.err and "boom" in out.err


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


def test_all_apps_searches_every_app_each_on_its_own_goal(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    changes = features(["train.py"], [TRAIN_STEP])
    target = seed(storage, app, verstr(1), changes=changes)
    mine = seed(storage, app, verstr(2), changes=changes, metrics={"val_loss": 0.3},
                goal=("val_loss", "min"))
    # The target's own verstr and code in another app: excluded in the target's app only.
    theirs = seed(storage, "other_app", target, changes=changes, metrics={"acc": 0.9},
                  goal=("acc", "max"))

    assert _verstrs(app_layout, capfd, "-v", target) == [mine]
    code, out = _similar(app_layout, capfd, "-v", target, "--all-apps", "--json")
    assert code == 0, out.err
    goals = {(i["app"], i["verstr"]): i["goal"]["metric"] for i in json.loads(out.out)}
    assert goals == {(app, mine): "val_loss", ("other_app", theirs): "acc"}
    code, out = _similar(app_layout, capfd, "-v", target, "--all-apps")
    assert any(line.startswith(f"other_app/{theirs}  ") for line in out.out.splitlines())


def _bootstrap_with_weights(app_layout, weights):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    app_layout.write_conf(params["app_conf_path"], experiment={"similar": {"weights": weights}})
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def _code_twins(app_layout):
    app, storage = app_layout.app_name, _storage(app_layout)
    changes = features(["train.py"], [TRAIN_STEP])
    return seed(storage, app, verstr(1), changes=changes), seed(
        storage, app, verstr(2), changes=changes)


def test_conf_weights_override_the_default_weights(app_layout, capfd):
    _bootstrap_with_weights(app_layout, {"code": 0, "files": 0, "symbols": 0})
    target, _ = _code_twins(app_layout)
    assert _verstrs(app_layout, capfd, "-v", target) == []


@pytest.mark.parametrize("weights", ["heavy", {"symbols": "lots", "nope": 1, "files": -2}])
def test_invalid_conf_weights_are_ignored(app_layout, capfd, weights):
    _bootstrap_with_weights(app_layout, weights)
    target, twin = _code_twins(app_layout)
    assert _verstrs(app_layout, capfd, "-v", target) == [twin]


# -- git-free (VMN_SNAPSHOT_METADATA) -------------------------------------------


@pytest.fixture
def container(tmp_path, monkeypatch):
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(yaml.safe_dump(
        {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": "trainer",
         "base_version": "1.2.0", "base_commit": "abc1234"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(meta))
    return tmp_path / "store"


def _git_free(store, capfd, *argv):
    capfd.readouterr()
    code = vmn_exp_run(["exp", *argv, "--experiment-dir", str(store)])[0]
    return code, capfd.readouterr()


def test_git_free_similar_takes_a_ref(container, capfd):
    code, out = _git_free(container, capfd, "create", "trainer", "--intent", "label smoothing")
    assert code == 0, out.err
    created = out.out.strip().splitlines()[-1]
    other = seed(open_storage(root=str(container), area="runs"), "trainer", verstr(1),
                 intent={"text": "label smoothing again"})

    code, out = _git_free(container, capfd, "similar", "trainer", "-v", created, "--json")
    assert code == 0, out.err
    assert [item["verstr"] for item in json.loads(out.out)] == [other]


def test_git_free_similar_without_a_ref_says_it_needs_one(container, capfd):
    assert _git_free(container, capfd, "create", "trainer")[0] == 0
    code, out = _git_free(container, capfd, "similar", "trainer")
    assert code == 1
    assert "-v" in out.err and "git checkout" in out.err
    code, out = _git_free(container, capfd, "similar", "trainer", "--context", "x", "--text-only")
    assert code == 0, out.err


def test_a_context_joins_the_working_trees_own_facts(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    body = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", body)
    changed = seed(storage, app, verstr(1), changes=features(["train.py"], [TRAIN_STEP]))
    smoothing = seed(storage, app, verstr(2), intent={"text": "label smoothing"})
    with open(app_layout.repo_path + "/train.py", "w") as f:
        f.write(body.replace("return {}", "return a"))

    assert _verstrs(app_layout, capfd) == [changed]
    assert sorted(_verstrs(app_layout, capfd, "--context", "label smoothing")) == sorted(
        [changed, smoothing])
