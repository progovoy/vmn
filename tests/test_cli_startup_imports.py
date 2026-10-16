"""Every vmn (and vmn-exp) command imports the CLI entry; only `vmn config`
prompts, so the prompt library must not load at startup (~0.13 s)."""
import subprocess
import sys

_CHECK = """
import sys
import version_stamp.cli.entry
print(sorted(m for m in ("questionary", "prompt_toolkit") if m in sys.modules))
"""


def test_the_cli_entry_does_not_load_the_prompt_library():
    out = subprocess.run([sys.executable, "-c", _CHECK], capture_output=True, text=True,
                         check=True, env={"PYTHONPATH": ":".join(sys.path)})
    assert out.stdout.strip() == "[]"
