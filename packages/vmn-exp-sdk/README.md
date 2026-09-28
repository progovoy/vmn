# vmn-exp-sdk

The metrics writer of the [vmn](https://github.com/progovoy/vmn) experiment
platform, for jobs: `start_run()`, `log_metric`/`log_params`/artifacts,
autologging and framework integrations — with no git and no vmn installed.

```sh
pip install vmn-exp-sdk          # add [s3] to record to a bucket
```

```python
from vmn_exp.sdk import start_run

with start_run("my_app") as run:   # VMN_SNAPSHOT_METADATA + VMN_EXPERIMENT_DIR/BUCKET
    run.log_metric("loss", 0.12)
```

Creating runs from a git checkout, the `vmn-exp` CLI and the dashboard live in
[`vmn-exp`](https://pypi.org/project/vmn-exp/). See
[docs/sdk.md](https://github.com/progovoy/vmn/blob/master/docs/sdk.md).
