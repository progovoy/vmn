"""A hyperparameter sweep as one outer run over several inner runs.

Shows:  nested=True — every run opened inside an open run becomes its child, so
        `vmn exp list` shows a tree and the outer run's tree_status rolls up the
        whole sweep (failed > stuck > running > created > succeeded).
Run:    python examples/03_sweep.py   (inside a git repo with a remote)
App:    writes runs to the vmn app "vmn_examples"
Next:   vmn exp list vmn_examples   (one outer job, three inner ones)
"""
from version_stamp.exp import start_run
from version_stamp.exp.reader import get_run

APP_NAME = "vmn_examples"
LEARNING_RATES = (0.0001, 0.0003, 0.001)


def train(lr):
    """Stand-in for a trial: a deterministic loss, best near lr=0.0003."""
    return round(0.2 + abs(lr - 0.0003) * 200, 4)


def main():
    with start_run(APP_NAME, note="lr sweep") as sweep:
        print(f"outer run: {sweep.id}")
        for lr in LEARNING_RATES:
            # nested=True parents this run to the innermost open one, which is
            # the sweep. No ids to pass around.
            with start_run(APP_NAME, nested=True, params={"lr": lr}) as trial:
                loss = train(lr)
                trial.log_metric("loss", loss)
                print(f"  trial lr={lr}: loss={loss} ({trial.id})")

        sweep.log_note(f"swept {len(LEARNING_RATES)} learning rates")

    outer = get_run(APP_NAME, ref=sweep.id)
    print(f"kind={outer['kind']} children={len(outer['children'])} "
          f"tree_status={outer['tree_status']}")
    print(f"see the tree with: vmn exp list {APP_NAME}")


if __name__ == "__main__":
    main()
