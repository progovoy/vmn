#!/usr/bin/env python3
"""The smallest useful vmn run: open one, log metrics, print its id.

Shows:  start_run() as a context manager, log_metric() with and without a step.
Run:    python examples/01_minimal.py   (from inside a git repo with a remote)
App:    writes runs to the vmn app "vmn_examples"
Next:   vmn exp list vmn_examples
"""
from version_stamp.exp import start_run

APP_NAME = "vmn_examples"


def main():
    with start_run(APP_NAME, note="minimal example") as run:
        for step, loss in enumerate([0.9, 0.5, 0.3, 0.2]):
            run.log_metric("loss", loss, step=step)
        run.log_metric("accuracy", 0.87)
        print(f"run id: {run.id}")

    print("logged: loss (4 steps), accuracy")
    print(f"see it with: vmn exp show {APP_NAME} {run.id}")


if __name__ == "__main__":
    main()
