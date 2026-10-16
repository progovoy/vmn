"""What similar runs answers — every item's score, reasons, signals, group
size and goal, and their order — is pinned on a varied synthetic corpus, so
work on how the answer is computed (memoized matches and pages, batched
stemming, paging) cannot change it unnoticed. The digest is of the FTS5
bm25 ranking of plan 24; a deliberate ranking change re-pins it."""
import hashlib
import json

from similar_fixtures import FakeSnapshot, changed, dataset, run, similar_runs, similar_runs_multi

WORDS = ("focal loss label smoothing mixup cutout warmup cosine schedule adam sgd "
         "dropout weight decay imbalance recall precision augmentation distill").split()
COMMANDS = (["python", "train.py", "fit", "--lr", "3"], ["python", "train.py", "eval"],
            ["torchrun", "--nproc", "8", "train.py"], ["bash", "sweep.sh"], None)
ANSWERS_DIGEST = "6a24a44e9c634b27d420d0988073060437e1d293eda271c3a2fc6ffb2d2c97c9"


def _words(i, n, step):
    return " ".join(WORDS[(i * step + k * 5) % len(WORDS)] for k in range(n))


def _row(app, i):
    verstr = f"1.{i % 7}.{i % 3}-dev.{i % 23:07d}.{i:07d}"
    return run(
        verstr, code=verstr if i % 5 else verstr.rsplit(".", 1)[0] + ".0000000",
        base=f"1.{i % 7}.{i % 3}", commit=f"{i % 23:07d}",
        parent=f"{app}-outer-{i // 9}" if i % 4 == 0 else None,
        timestamp=f"2026-0{1 + i % 9}-{1 + i % 27:02d}T00:00:00Z",
        name=f"run {_words(i, 2, 3)}" if i % 2 else None,
        note=_words(i, 4, 7) if i % 3 else None,
        branch=("main", "feat/focal", None)[i % 3],
        params={"lr": (1e-4, 3e-4, 1e-3, "auto")[i % 4], "bs": (16, 32)[i % 2],
                "amp": bool(i % 2), f"p{i % 6}": i % 5},
        metrics={"val_loss": (i % 13) / 13.0, "acc": (i % 11) / 11.0, "sys_cpu": 1.0},
        inputs={**dataset(f"ds{i % 5}@{i % 3}", f"sha256:{i % 17}"),
                **(dataset("bert@1", f"sha256:m{i % 4}", kind="model") if i % 6 == 0 else {})},
        tags={"team": f"t{i % 4}"}, command=COMMANDS[i % len(COMMANDS)],
    )


def _corpus(app, n):
    rows = [_row(app, i) for i in range(n)]
    features, intents, hypotheses = {}, {}, {}
    for i, row in enumerate(rows):
        verstr = row["verstr"]
        if i % 5 == 0:
            features[verstr] = changed()
        elif i % 7:
            features[verstr] = changed(
                files=[f"src/m{i % 31}.py", f"src/m{(i * 3) % 31}.py"],
                symbols=[f"src/m{i % 31}.py::f{i % 41}", f"src/m{i % 31}.py::g{i % 13}"],
                commits=[_words(i, 3, 11)],
                **({"changed_source": "commit"} if i % 9 == 0 else {}))
        if i % 4 == 0:
            intents[verstr] = {"text": _words(i, 8, 13), "keywords": [WORDS[i % 18], "label smoothing"]}
        if i % 10 == 0:
            hypotheses[verstr] = _words(i, 5, 17)
    states = {r["verstr"]: {"command": ["python", "train.py", "fit"]} for r in rows[::11]}
    snapshot = FakeSnapshot(rows, features=features, intents=intents, hypotheses=hypotheses,
                            declared={"val_loss": {"goal": "min"}}, run_states=states,
                            create_notes={r["verstr"]: "first try" for r in rows[::8]})
    return snapshot, rows


def _target(snapshot, row, **extra):
    verstr = row["verstr"]
    return dict({"row": row, "features": snapshot.features_of(verstr),
                 "intent": snapshot.intent_of(verstr), "hypothesis": snapshot.hypothesis_of(verstr),
                 "text": None, "text_only": False}, **extra)


def _answers():
    snapshot, rows = _corpus("a", 1500)
    other, _ = _corpus("b", 600)
    tree = {"row": {"code_verstr": "1.2.0-dev.0000004.1234567", "base_version": "1.2.0",
                    "branch": "main"},
            "features": changed(files=["src/m4.py"], symbols=["src/m4.py::f4"]),
            "command": ["python", "train.py", "fit"], "text": None, "text_only": False}
    queries = [
        (_target(snapshot, rows[8]), None),
        (_target(snapshot, rows[13]), None),
        (_target(snapshot, rows[27]), None),
        (_target(snapshot, rows[13], text="focal loss imbalance"), None),
        (_target(snapshot, rows[44]), {"params": 4, "text": 0.5, "bogus": 1}),
        (_target(snapshot, rows[44]), "not a mapping"),
        (_target(snapshot, rows[9]), {"files": 0}),
        (tree, None),
        ({"row": None, "text": "label smoothing focal recall", "text_only": True}, None),
    ]
    answers = [_shown(similar_runs(snapshot, target, top=10, weights=weights, app="a"))
               for target, weights in queries]
    scopes = [("a", snapshot, None), ("b", other, {"acc": {"goal": "max"}})]
    answers.append(_shown(similar_runs_multi(scopes, dict(_target(snapshot, rows[16]), app="a"),
                                             top=15)))
    answers.append(_shown(similar_runs_multi(scopes, queries[-1][0], top=15)))
    return answers


def _shown(items):
    return [[i["app"], i["verstr"], i["score"], i["reasons"], i["signals"], i["group_size"],
             i["goal"]] for i in items]


def test_similar_runs_answers_what_it_answered_before():
    answers = _answers()
    assert all(answers) and len(answers) == 11
    digest = hashlib.sha256(json.dumps(answers, sort_keys=True).encode()).hexdigest()
    assert digest == ANSWERS_DIGEST
