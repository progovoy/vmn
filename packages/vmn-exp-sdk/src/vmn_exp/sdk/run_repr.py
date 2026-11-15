"""How a run shows itself: one line for a REPL, a log or a debugger, and a
small HTML block for a notebook (Jupyter calls ``_repr_html_`` by name).

Pure functions over plain values: a repr never touches storage and never
raises. The state is this process's view, not the derived status.
"""
from html import escape


def _outcome(state, exit_code):
    return state if exit_code is None else f"{state} exit {exit_code}"


def text(app_name, run_id, name, state, exit_code):
    named = f' "{name}"' if name else ""
    return f"<Run {app_name} {run_id}{named} {_outcome(state, exit_code)}>"


def html(app_name, run_id, name, state, exit_code):
    rows = [("app", app_name), ("run", run_id)]
    if name:
        rows.append(("name", name))
    rows.append(("state", _outcome(state, exit_code)))
    cells = "".join(
        f"<tr><th style='text-align:left'>{key}</th><td>{escape(str(value))}</td></tr>"
        for key, value in rows
    )
    command = escape(f"vmn-exp show {app_name} -v {run_id}")
    return f"<div><table>{cells}</table><code>{command}</code></div>"


def noop_text(app_name, disabled, rank):
    why = "disabled" if disabled else f"rank {rank}"
    return f"<NoOpRun {app_name} records nothing: {why}>"
