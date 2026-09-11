# README demo

`vmn-goto.gif` shows a two-dependency release being stamped and then restored
with `vmn goto`. Regenerate it after installing [VHS](https://github.com/charmbracelet/vhs):

```sh
pip install -e .          # or pipx install vmn
demo/setup.sh             # scratch workspace in /tmp/vmn-demo
vhs demo/demo.tape        # writes demo/vmn-goto.gif
```

`setup.sh` creates three repos with bare remotes under `/tmp/vmn-demo`
(`shop` plus its dependencies `lib_core` and `service_api`) and configures
`shop` to track the other two. The tape then runs the release/restore flow.
