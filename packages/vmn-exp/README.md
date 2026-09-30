# vmn-exp

The experiment platform built on [vmn](https://github.com/progovoy/vmn): the
`vmn-exp` command (experiments, model registry, snapshots), the web dashboard,
and capturing runs from a git checkout.

```sh
pip install vmn-exp              # add [ui] for the dashboard, [s3] for buckets
vmn-exp run my_app -- python train.py
vmn-exp list my_app --sort loss
vmn-exp ui
```

Jobs that only record metrics need just
[`vmn-exp-sdk`](https://pypi.org/project/vmn-exp-sdk/). See
[docs/vmn-exp](https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/README.md).
