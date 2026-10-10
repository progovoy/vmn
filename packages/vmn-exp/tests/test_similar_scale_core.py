"""Similar runs stay interactive on a large app: 20k runs, index build included."""
import random
import time

from similar_fixtures import FakeSnapshot, changed, dataset, run
from vmn_exp.core.similar import similar_runs

WORDS = ("focal loss label smoothing mixup cutout warmup cosine schedule adam sgd "
         "dropout weight decay imbalance recall precision augmentation distill").split()


def _synthetic(n, seed=7):
    rnd = random.Random(seed)
    rows, features, intents = [], {}, {}
    for i in range(n):
        verstr = f"1.{i % 40}.0-dev.{i % 97:07d}.{i:07d}.1"
        rows.append(run(
            verstr, code=verstr.rsplit(".", 1)[0], base=f"1.{i % 40}.0",
            parent=f"1.0.0-dev.outer.{i // 50}" if i % 3 == 0 else None,
            timestamp=f"2026-01-{1 + i % 28:02d}T00:00:{i % 60:02d}Z",
            params={"lr": rnd.choice([1e-4, 3e-4, 1e-3]), "bs": rnd.choice([16, 32]),
                    f"p{i % 30}": i % 5},
            metrics={"val_loss": rnd.random(), "acc": rnd.random(), f"m{i % 20}": 1.0},
            inputs=dataset(f"ds{i % 15}@{i % 4}", f"sha256:{i % 60}"),
            note=" ".join(rnd.sample(WORDS, 4)),
            tags={"team": f"t{i % 9}"},
        ))
        features[verstr] = changed(
            files=[f"src/m{i % 120}.py", f"src/m{(i * 7) % 120}.py"],
            symbols=[f"src/m{i % 120}.py::f{i % 300}"],
            commits=[" ".join(rnd.sample(WORDS, 3))],
        )
        if i % 4 == 0:
            intents[verstr] = {"text": " ".join(rnd.sample(WORDS, 8)),
                               "keywords": rnd.sample(WORDS, 2)}
    snapshot = FakeSnapshot(rows, features=features, intents=intents,
                            declared={"val_loss": {"goal": "min"}})
    return snapshot, rows


def test_a_query_over_twenty_thousand_runs_takes_well_under_seconds():
    snapshot, rows = _synthetic(20000)
    target = {"row": rows[123], "features": snapshot.features_of(rows[123]["verstr"]),
              "intent": snapshot.intent_of(rows[123]["verstr"]), "hypothesis": None,
              "text": None, "text_only": False}
    started = time.perf_counter()
    items = similar_runs(snapshot, target, top=10)
    cold = time.perf_counter() - started
    started = time.perf_counter()
    similar_runs(snapshot, dict(target, text="focal loss imbalance"), top=10)
    warm = time.perf_counter() - started
    assert len(items) == 10
    assert cold < 5.0, cold
    assert warm < 2.0, warm
