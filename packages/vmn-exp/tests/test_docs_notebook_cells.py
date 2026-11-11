"""The notebook guide (docs/vmn-exp/notebooks.md) is linked from the docs, and
its numbered cells run as written (plan 38 A9).

A guide cell is a ```python block whose first line is ``# Cell N``; the other
python blocks are alternatives or later fixes and are not run in sequence.
"""
import json
import os
import re
import subprocess

from exp_helpers import _PROJECT_ROOT, _PY, _SRC_PATH

from vmn_exp.sdk.checkout_guard import not_a_checkout

GUIDE = "docs/vmn-exp/notebooks.md"
GUIDE_APP = "my_app"
_RUN_ID = re.compile(r"'[^']*'")
_CLEARED_ENV = ("VMN_WORKING_DIR", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_RESUME_RUN_ID", "VMN_EXPERIMENT_ID", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXP_OFFLINE")

_RUN_CELLS = """
import json, sys
namespace = {}
for cell in json.loads(sys.argv[1]):
    exec(compile(cell, "<cell>", "exec"), namespace)
"""


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _fenced(text, lang):
    return re.findall(rf"^```{lang}\n(.*?)^```$", text, re.M | re.S)


def _cells(text):
    return [b for b in _fenced(text, "python") if b.startswith("# Cell ")]


def _documented_error(text, needle):
    """The message of the quoted ``RuntimeError: ...`` line containing *needle*."""
    prefix = "RuntimeError: "
    for block in _fenced(text, "text"):
        for line in block.splitlines():
            if line.startswith(prefix) and needle in line:
                return line[len(prefix):]
    raise AssertionError(f"the guide quotes no RuntimeError with '{needle}'")


def _run_cells(cells, app_layout):
    cells = [c.replace(GUIDE_APP, app_layout.app_name) for c in cells]
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED_ENV}
    return subprocess.run(
        [_PY, "-c", _RUN_CELLS, json.dumps(cells)], cwd=app_layout.repo_path,
        capture_output=True, text=True, env={**env, "PYTHONPATH": _SRC_PATH},
    )


def test_notebook_guide_is_linked_from_the_docs_index_client_guide_and_sdk():
    for doc in ("docs/vmn-exp/README.md", "docs/vmn-exp/client-guide.md",
                "docs/vmn-exp/sdk.md"):
        assert "(notebooks.md" in _read(doc), doc
    assert "`notebooks.md`" in _read("CLAUDE.md")


def test_the_guide_quotes_the_not_a_checkout_error():
    quoted = _documented_error(_read(GUIDE), "not inside a git checkout")
    assert quoted == not_a_checkout("/home/me/scratch")


def test_the_guides_cells_run_in_order_in_one_interpreter_and_record_one_run(app_layout):
    cells = _cells(_read(GUIDE))
    assert len(cells) >= 3
    check = ("from vmn_exp.sdk.reader import list_runs\n"
             f"print(json.dumps([r['status'] for r in list_runs({GUIDE_APP!r})]))\n")
    proc = _run_cells([*cells, "import json\n" + check], app_layout)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == ["succeeded"]


def test_rerunning_the_start_cell_raises_the_documented_error_text(app_layout):
    start = _cells(_read(GUIDE))[0]
    catch = ("try:\n" + "".join(f"    {line}\n" for line in start.splitlines())
             + "except RuntimeError as exc:\n    print(exc)\n")
    proc = _run_cells([start, catch], app_layout)
    assert proc.returncode == 0, proc.stderr
    documented = _documented_error(_read(GUIDE), "is already active")
    actual = proc.stdout.strip().splitlines()[-1]
    assert _RUN_ID.sub("'<id>'", actual) == _RUN_ID.sub("'<id>'", documented)
