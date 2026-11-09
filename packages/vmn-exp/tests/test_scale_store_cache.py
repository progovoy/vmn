"""scale_store.cached / derived: the shared scale store in the cache dir is
built once, atomically, by one builder at a time, rebuilt when found partial
(the OS's temp cleaner deletes files and keeps directories), and the files
derived from it (a built index) go with it."""
import os
import subprocess
import sys

import pytest
import scale_store
from exp_helpers import _SRC_PATH
from vmn_exp.storage.areas import local_store_root

N = 30


def _runs_dir(root):
    return os.path.join(local_store_root(root), "runs", scale_store.APP)


def _purge_files(root):
    """What the OS's temp cleaner leaves of a store: its directories."""
    for folder, _, files in os.walk(root):
        for name in files:
            os.remove(os.path.join(folder, name))


def _is_whole(root):
    runs = os.listdir(_runs_dir(root))
    return len(runs) == N and all(
        os.path.exists(os.path.join(_runs_dir(root), run, "metadata.yml")) for run in runs)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_SCALE_STORE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


def test_a_store_left_without_its_files_is_rebuilt(cache):
    root = scale_store.cached(N, workers=1)
    _purge_files(root)
    assert scale_store.cached(N, workers=1) == root
    assert _is_whole(root)


def test_a_store_missing_a_runs_metadata_is_rebuilt(cache):
    root = scale_store.cached(N, workers=1)
    run = sorted(os.listdir(_runs_dir(root)))[3]
    os.remove(os.path.join(_runs_dir(root), run, "metadata.yml"))
    scale_store.cached(N, workers=1)
    assert _is_whole(root)


def test_an_interrupted_build_leaves_nothing_behind(cache, monkeypatch):
    def interrupted(root, n, **kwargs):
        os.makedirs(os.path.join(root, "half-written"))
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(scale_store, "generate", interrupted)
        with pytest.raises(KeyboardInterrupt):
            scale_store.cached(N, workers=1)
    root = scale_store.cached(N, workers=1)
    assert _is_whole(root)
    name = os.path.basename(root)
    assert sorted(os.listdir(cache)) == [name, name + ".lock"]


def _counting(calls):
    def build(root, path):
        calls.append(root)
        with open(path, "w") as f:
            f.write(str(len(os.listdir(_runs_dir(root)))))
    return build


def test_a_derived_file_is_built_once_per_store(cache):
    calls = []
    root, path = scale_store.derived(N, "count.txt", _counting(calls), workers=1)
    assert scale_store.derived(N, "count.txt", _counting(calls), workers=1) == (root, path)
    assert calls == [root]
    assert open(path).read() == str(N)


def test_a_rebuilt_store_drops_the_files_derived_from_it(cache):
    calls = []
    root, path = scale_store.derived(N, "count.txt", _counting(calls), workers=1)
    _purge_files(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("0")  # derived from the broken store
    assert scale_store.derived(N, "count.txt", _counting(calls), workers=1) == (root, path)
    assert len(calls) == 2
    assert open(path).read() == str(N)


_BUILDER = """
import sys
sys.path[:0] = sys.argv[2].split({sep!r})
import scale_store
generate = scale_store.generate
def counted(*args, **kwargs):
    with open(sys.argv[1], "a") as f:
        f.write("built\\n")
    return generate(*args, **kwargs)
scale_store.generate = counted
print(scale_store.cached({n}, workers=1))
"""


def test_concurrent_builders_generate_the_store_once(cache, tmp_path):
    counter = tmp_path / "builds"
    path = os.pathsep.join([os.path.dirname(os.path.abspath(__file__)), _SRC_PATH])
    code = _BUILDER.format(sep=os.pathsep, n=N)
    env = dict(os.environ, VMN_SCALE_STORE_DIR=str(cache))
    builders = [subprocess.Popen([sys.executable, "-c", code, str(counter), path],
                                 env=env, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    roots = {builder.communicate(timeout=120)[0].strip() for builder in builders}
    assert [builder.returncode for builder in builders] == [0] * 4
    assert len(roots) == 1
    assert counter.read_text() == "built\n"
    assert _is_whole(roots.pop())
