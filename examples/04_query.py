"""Find runs again: the query language, over runs this script just created.

Shows:  list_runs(query=...) with a metric threshold, a string param, and a
        status set — plus how a crashed run is recorded as failed.
Run:    python examples/04_query.py   (inside a git repo with a remote)
App:    writes runs to the vmn app "vmn_examples"
Next:   re-run it — every query is scoped to params.example, so the counts grow
        by the same four runs each time.
"""
from version_stamp.exp import start_run
from version_stamp.exp.reader import list_runs

APP_NAME = "vmn_examples"

# The last one crashes on purpose, to have a failed run to query for.
TRIALS = (
    {"model": "linear", "loss": 0.62, "crash": False},
    {"model": "xgb", "loss": 0.31, "crash": False},
    {"model": "xgb", "loss": 0.72, "crash": False},
    {"model": "linear", "loss": 0.90, "crash": True},
)

SCOPE = 'params.example = "04_query"'
QUERIES = (
    SCOPE,
    f"metrics.loss < 0.5 and {SCOPE}",
    f'params.model = "xgb" and {SCOPE}',
    f'status in ("failed", "stuck") and {SCOPE}',
)


def create_trials():
    for trial in TRIALS:
        params = {"example": "04_query", "model": trial["model"]}
        try:
            with start_run(APP_NAME, params=params) as run:
                run.log_metric("loss", trial["loss"])
                if trial["crash"]:
                    raise RuntimeError("diverged")
        except RuntimeError as exc:
            # The SDK records the run as failed and re-raises — it never
            # swallows your exception.
            print(f"  run failed as expected: {exc}")


def print_rows(rows):
    print(f"  {'verstr':<34} {'status':<10} {'model':<8} loss")
    for row in rows:
        loss = row["metrics"].get("loss")
        print(
            f"  {row['verstr']:<34} {row['status']:<10} "
            f"{row['params'].get('model', '-'):<8} {loss}"
        )
    print(f"matched {len(rows)} run{'' if len(rows) == 1 else 's'}")


def main():
    create_trials()
    print(f"created {len(TRIALS)} runs\n")

    for query in QUERIES:
        print(f"query: {query}")
        print_rows(list_runs(APP_NAME, query=query))
        print()

    print("field names are case-sensitive and unknown ones raise QueryError,")
    print("so a typo tells you instead of returning an empty list.")


if __name__ == "__main__":
    main()
