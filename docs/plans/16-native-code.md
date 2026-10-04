# 16 — Native code (Rust): when it would pay off

Status: **evaluation 2026-10-04, no work scheduled.** Records where Rust would and would not
help, so the question doesn't have to be re-investigated. Do [15-core-cli-speedups.md](15-core-cli-speedups.md)
first, whatever happens here.

Paths are under `packages/`; `S` = `vmn-exp-sdk/src/vmn_exp`.

---

## 1. Core vmn: not worth it piecemeal

A `vmn show` spends ~160 ms importing Python modules and ~130 ms waiting on `git` processes.
vmn's own logic takes a few ms (numbers in [plan 15 §1](15-core-cli-speedups.md#1-baseline)).
Moving hot functions into a PyO3 extension would speed up those few ms. It wouldn't touch
imports or process spawning, and would add per-platform wheels and a Rust toolchain to the
release. **Rejected.**

## 2. Core vmn: a full rewrite as a single static binary

The one Rust option that pays off for core.

- **What:** the `vmn` CLI as one Rust binary, reading git in-process with
  [`gix`](https://github.com/GitoxideLabs/gitoxide) (refs, tag objects, commit walks) instead of
  spawning `git`. Writes (commit, tag, push) can keep shelling out to `git` so credentials,
  hooks and signing behave as users expect.
- **Gain:** ~10 ms startup, no Python runtime on the host. That fits the
  "language-agnostic" pitch: a Go/Rust/JS shop installs one binary (`brew`, `cargo install`,
  a GitHub release asset, or a PyPI wheel the way `git-cliff` already ships; it is a vmn
  dependency today).
- **The gain is distribution, not speed.** After plan 15, Python vmn should be ~150–200 ms,
  which is fine for a release tool that runs a few times per pipeline.
- **Cost:**
  - Two implementations of the tag format, version math, conf/branch-conf resolution,
    backends (`package.json`, `Cargo.toml`, `pyproject.toml`, regex/Jinja2), changelog and
    GitHub releases, islands and `goto`. Or one implementation, giving up the Python library
    API (`version_stamp.api`), which vmn-exp is built on (snapshots, `register_dev_version`,
    `restore_record`, `run_skill`).
  - Jinja2 templates (`vmn gen`, `version_backends`) would need a compatible engine
    (`minijinja` is close but not identical).
  - The core test suite is Python driving the CLI. It could stay as the spec for both
    implementations, but the fixtures that call internals would not carry over.
- **Possible middle path, if pursued:** a Rust binary covering the read-only commands
  (`show`, `--version`, completion) and handing the rest to Python. It keeps one source of
  truth for writes, but two for reads, and the tag-format parser must match exactly.

**Decision trigger:** real user demand for a Python-free install (issues, adoption feedback
from non-Python teams), not performance. Until then, no.

## 3. vmn-exp: where native code could buy 10–100×

The number-crunching lives in vmn-exp, not core. It is all pure Python today; vmn-exp-sdk
depends only on PyYAML, filelock and psutil, with no numpy.

| Hot path | Where | Why it may be slow |
|---|---|---|
| Metric compaction: streams → indexed `.vmx` with sorted chunks + min/max LOD pyramid + footer | `S/core/metric_compact.py`, `metric_lod.py`, `metric_index_file.py` | Per-point Python loops over up to 10M points per part; runs inside the SDK's final upload wait |
| Index rebuild / fold at 100k runs | `S/core/index*.py`, `core/metric_summary.py` | Per-run, per-metric folds; the UI already recommends free-threaded 3.14t for throughput |
| Parameter importance | `S/core/importance.py` (pure-Python histogram random forest + Pearson/Spearman) | Tree building over runs × params in interpreted loops |
| Series reads / downsampling for the UI | `S/core/series_reader.py`, `metric_index_reader.py` | Decoding chunks and LOD selection per request |

### Before writing any Rust

1. **Measure.** Add benchmarks (pytest-benchmark or a `tests/uiload`-style harness) for each
   row at realistic sizes: 10M-point compaction, 100k-run index rebuild, importance over 10k
   runs × 50 params, a 1M-point series read. Record wall time and peak RSS.
2. **Try cheaper options first, per row:**
   - `array`/`struct.iter_unpack`/`memoryview` bulk ops instead of per-point loops (no new
     dependency).
   - Free-threaded 3.14t + the existing worker pools for the index.
   - Optional numpy (an extra, like `[pandas]`) for importance and LOD, with the pure-Python
     path kept as the fallback.
3. **Only then** consider a Rust extension for whatever remains slow.

### If a Rust extension is justified

- One optional crate (e.g. `vmn-exp-native`, built with maturin, abi3 wheels for
  linux x86_64/aarch64, macOS arm64/x86_64, Windows). vmn-exp-sdk imports it if present and
  falls back to pure Python, so source installs and odd platforms keep working.
- The `.vmx` format stays specified by the Python implementation. The Rust side must
  produce byte-identical files; a golden-file test runs both implementations on the same input.
- Free-threading: release the GIL in the extension and declare `Py_MOD_GIL_NOT_USED` so 3.14t
  keeps its scaling.
- Import rules (`packages/vmn-exp/tests/test_packaging_split.py`) extend to the crate: the
  SDK may depend on it, `version_stamp` never does.

**Decision trigger:** a benchmark from step 1 showing a user-visible cost (SDK `finish()`
blocking on compaction, UI cold start at 100k runs, importance view latency) that steps 2's
options don't fix.
