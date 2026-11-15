# vmn-exp

The experiment platform built on [vmn](https://github.com/progovoy/vmn): the
`vmn-exp` command (experiments, model registry, snapshots), the web dashboard,
and capturing runs from a git checkout.

## Quickstart

In a git repo with at least one commit and a git identity:

```sh
pip install "vmn-exp[ui]"        # [ui] is the dashboard; add [s3] for buckets
git init demo && cd demo && git commit --allow-empty -m init
```

`train.py`:

```python
from vmn_exp.sdk import start_run

with start_run("my_app") as run:
    for step in range(5):
        run.log_metric("loss", 1.0 / (step + 1), step=step)
    print(run.id)
```

```sh
python train.py
vmn-exp list my_app --sort loss
vmn-exp ui                       # http://127.0.0.1:8265
```

The first run commits vmn's init files and tags `my_app_0.0.0` locally;
nothing is pushed. To wrap a script you cannot edit, use
`vmn-exp run my_app -- python train.py`; as the app's first run it also pushes
that baseline when the repo has a remote. Without a git checkout, see
[the SDK guide](https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/sdk.md#runs-without-a-git-checkout-containers).

Jobs that only record metrics need just
[`vmn-exp-sdk`](https://pypi.org/project/vmn-exp-sdk/). See
[docs/vmn-exp](https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/README.md).
