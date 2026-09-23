"""Autologging: a real sklearn fit recorded without a single logging call.

Shows:  autolog() patches the framework's fit(), so hyperparameters, the training
        score and the pickled model land on the open run by themselves. It
        records only while a run is open and never opens one for you.
Run:    python examples/05_autolog_sklearn.py   (inside a git repo with a remote)
App:    writes runs to the vmn app "vmn_examples"
Next:   vmn exp show vmn_examples --latest   (the sklearn_* params and artifact)
"""
from version_stamp.exp import autolog, start_run
from version_stamp.exp.reader import get_run

APP_NAME = "vmn_examples"

# A toy separable dataset, so nothing is downloaded and the fit is instant.
X = [
    [0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [0.3, 0.0],
    [1.0, 1.0], [0.9, 1.1], [1.1, 0.9], [1.2, 1.0],
]
Y = [0, 0, 0, 0, 1, 1, 1, 1]


def main():
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("This example needs scikit-learn: pip install scikit-learn")
        return

    # Safe to call at import time: naming a framework that is not installed is a
    # silent no-op. Saving the model is opt-in (log_models=True).
    autolog(frameworks=["sklearn"], log_models=True)

    with start_run(APP_NAME, note="autologged logistic regression") as run:
        LogisticRegression(C=2.0, max_iter=200).fit(X, Y)
        print(f"run id: {run.id}")

    recorded = get_run(APP_NAME, ref=run.id)
    for key, value in sorted(recorded["params"].items()):
        if key.startswith("sklearn_"):
            print(f"  {key} = {value}")
    print(f"  metrics.sklearn_score = {recorded['metrics'].get('sklearn_score')}")
    for artifact in recorded["artifacts"]:
        print(f"  artifact: {artifact['name']}")


if __name__ == "__main__":
    main()
