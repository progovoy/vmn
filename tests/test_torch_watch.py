"""``torch_watch.watch(model)``: gradient/parameter histograms for plain torch."""
import subprocess
import sys

import pytest

torch = pytest.importorskip("torch")

from vmn_exp.core.histogram import histogram
from vmn_exp.core.media import MAX_HISTOGRAM_STEPS, media_index
from vmn_exp.integrations import torch_watch
from vmn_exp.integrations.torch_watch import unwatch, watch
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.ccccccc"


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "experiments"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


@pytest.fixture
def run(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    yield run
    run.finish()


@pytest.fixture
def model():
    torch.manual_seed(0)
    return torch.nn.Linear(3, 2)


def _train(model, steps):
    for _ in range(steps):
        model.zero_grad()
        model(torch.randn(4, 3)).sum().backward()


def _histograms(run, storage):
    run.finish()
    return [e for e in storage.load_merged_log(APP, VERSTR) if e["type"] == "histogram"]


def _steps(entries, name):
    return [e["step"] for e in entries if e["name"] == name]


def test_import_does_not_import_torch():
    code = "import sys, vmn_exp.integrations.torch_watch; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_gradients_logged_every_freq_steps(run, storage, model):
    watcher = watch(model, freq=2)
    _train(model, 4)
    watcher.flush()
    entries = _histograms(run, storage)
    assert _steps(entries, "gradients/weight") == [2, 4]
    assert _steps(entries, "gradients/bias") == [2, 4]
    assert all(sum(e["counts"]) == 6 for e in entries if e["name"] == "gradients/weight")
    assert not [e for e in entries if e["name"].startswith("parameters/")]


def test_parameters_mode_logs_only_parameters(run, storage, model):
    watcher = watch(model, log="parameters", freq=1)
    _train(model, 1)
    watcher.flush()
    entries = _histograms(run, storage)
    assert sorted(e["name"] for e in entries) == ["parameters/bias", "parameters/weight"]
    assert sum(next(e for e in entries if e["name"] == "parameters/bias")["counts"]) == 2


def test_all_mode_logs_both(run, storage, model):
    watcher = watch(model, log="all", freq=1, prefix="net/")
    _train(model, 1)
    watcher.flush()
    names = sorted(e["name"] for e in _histograms(run, storage))
    assert names == [
        "net/gradients/bias", "net/gradients/weight",
        "net/parameters/bias", "net/parameters/weight",
    ]


def test_unknown_mode_is_refused(model):
    with pytest.raises(ValueError, match="log"):
        watch(model, log="everything")


def test_eval_mode_forward_is_not_counted(run, storage, model):
    watcher = watch(model, log="parameters", freq=1)
    model.eval()
    with torch.no_grad():
        model(torch.randn(2, 3))
        model(torch.randn(2, 3))
    model.train()
    _train(model, 1)
    watcher.flush()
    assert _steps(_histograms(run, storage), "parameters/weight") == [1]


def test_no_open_run_records_nothing_and_training_works(model):
    watcher = watch(model, log="all", freq=1)
    _train(model, 2)
    watcher.flush()
    assert model.weight.grad is not None


def test_hook_failure_never_breaks_backward(run, storage, model, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(torch_watch, "_tensor_histogram", boom)
    watcher = watch(model, log="all", freq=1)
    _train(model, 2)
    watcher.flush()
    assert model.weight.grad is not None
    assert _histograms(run, storage) == []


def test_gradients_are_unchanged_by_hook(run, model):
    x = torch.randn(4, 3)
    model(x).sum().backward()
    expected = model.weight.grad.clone()
    model.zero_grad()
    watch(model, freq=1)
    model(x).sum().backward()
    assert torch.equal(model.weight.grad, expected)


def test_rewatch_replaces_hooks(run, storage, model):
    watch(model, log="all", freq=1)
    watcher = watch(model, log="all", freq=1)
    assert len(model._forward_pre_hooks) == 1
    _train(model, 1)
    watcher.flush()
    assert _steps(_histograms(run, storage), "gradients/weight") == [1]


def test_remove_detaches_all_hooks(run, storage, model):
    watch(model, log="all", freq=1)
    unwatch(model)
    assert len(model._forward_pre_hooks) == 0
    assert not model.weight._backward_hooks
    _train(model, 2)
    assert _histograms(run, storage) == []


def test_remove_flushes_pending_gradients(run, storage, model):
    watcher = watch(model, freq=1)
    _train(model, 1)
    unwatch(watcher)
    assert _steps(_histograms(run, storage), "gradients/weight") == [1]


def test_tensor_histogram_matches_core_histogram_bins():
    values = torch.tensor([[0.1, 0.5, 0.9], [2.3, 3.7, 3.7]])
    got = torch_watch._tensor_histogram(values, 4)
    want = histogram(values.numpy(), bins=4)
    assert got["counts"] == want["counts"]
    assert got["bins"] == pytest.approx(want["bins"], rel=1e-6)


def test_tensor_histogram_widens_a_constant_and_skips_non_finite():
    values = torch.tensor([2.0, 2.0, float("nan"), float("inf")])
    got = torch_watch._tensor_histogram(values, 2)
    assert got["bins"] == pytest.approx([1.5, 2.0, 2.5])
    assert sum(got["counts"]) == 2
    assert torch_watch._tensor_histogram(torch.tensor([float("nan")]), 2) is None


def test_entries_index_per_name_with_thinning(run, storage, model):
    steps = MAX_HISTOGRAM_STEPS * 2 + 50
    watcher = watch(model, freq=1)
    _train(model, steps)
    watcher.flush()
    run.finish()
    index = media_index(storage.load_merged_log(APP, VERSTR))
    assert index["histograms_total"]["gradients/weight"] == steps
    served = [i["step"] for i in index["histograms"]["gradients/weight"]]
    assert len(served) == MAX_HISTOGRAM_STEPS
    assert served[0] == 1 and served[-1] == steps
