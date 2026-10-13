"""One xdist worker runs both the torch and the xgboost tests. On macOS each
brings its own libomp, and two OpenMP runtimes in one process crash whichever
runs a parallel region second — so the runners load torch's for both."""
import pytest


def test_xgboost_and_torch_run_in_one_process_in_either_order():
    xgboost = pytest.importorskip("xgboost")
    torch = pytest.importorskip("torch")
    np = pytest.importorskip("numpy")

    xgboost.XGBClassifier(n_estimators=2).fit(np.random.rand(200, 3), np.arange(200) % 2)
    out = torch.nn.functional.layer_norm(torch.randn(512, 768), (768,))
    xgboost.XGBRegressor(n_estimators=2).fit(np.random.rand(200, 3), np.random.rand(200))

    assert out.shape == (512, 768)
