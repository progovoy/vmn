"""Every thread pool of the SDK names its threads: the diag dump attributes
S3 calls and stacks by thread name, and ``ThreadPoolExecutor-3_7`` says
nothing about which code issued them."""
import ast
import pathlib

SDK = pathlib.Path(__file__).resolve().parents[2] / "vmn-exp-sdk" / "src" / "vmn_exp"


def _unnamed_pools():
    for path in SDK.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ThreadPoolExecutor"
                    and not any(k.arg == "thread_name_prefix" for k in node.keywords)):
                yield f"{path.relative_to(SDK)}:{node.lineno}"


def test_every_sdk_pool_names_its_threads():
    assert list(_unnamed_pools()) == []
