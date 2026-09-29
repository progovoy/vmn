"""A trial's command line, from the spec's (or the agent's) template.

The template is a list of strings (one argv entry each). Placeholders:

* ``${<param>}`` anywhere in an entry: that param's value;
* ``${args}`` (a whole entry): ``--name=value`` per param, sorted by name;
* ``${args_no_hyphens}``: ``name=value`` per param; ``${args_json}``: one
  JSON entry with every param;
* ``${interpreter}``: the agent's Python; ``${program}``: the spec's
  ``program``; ``${env}``: nothing (W&B writes ``/usr/bin/env`` there).

Without a template, a spec with ``program`` runs W&B's default
``${env} ${interpreter} ${program} ${args}``.
"""
import json
import re
import sys

from vmn_exp.core.sweep.spec import SpecError

DEFAULT_TEMPLATE = ["${env}", "${interpreter}", "${program}", "${args}"]
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z0-9_.]+)\}")


def trial_command(spec, params, override=None):
    """The argv for a trial with *params*; *override* is ``agent -- cmd...``."""
    require_command(spec, override)
    template = override or spec.get("command") or DEFAULT_TEMPLATE
    argv = []
    for token in template:
        argv.extend(_expand(token, params, spec))
    return argv


def require_command(spec, override=None):
    """SpecError unless a trial has a command to run."""
    if not (override or spec.get("command") or spec.get("program")):
        raise SpecError("No command: give the spec a command: or program:, "
                        "or pass one after -- to sweep agent")


def _expand(token, params, spec):
    names = sorted(params)
    if token == "${env}":
        return []
    if token == "${args}":
        return [f"--{k}={_text(params[k])}" for k in names]
    if token == "${args_no_hyphens}":
        return [f"{k}={_text(params[k])}" for k in names]
    if token == "${args_json}":
        return [json.dumps({k: params[k] for k in names})]
    return [_PLACEHOLDER.sub(lambda m: _lookup(m.group(1), params, spec), token)]


def _lookup(name, params, spec):
    if name in params:
        return _text(params[name])
    if name == "interpreter":
        return sys.executable
    if name == "program" and spec.get("program"):
        return str(spec["program"])
    raise SpecError(f"Unknown placeholder ${{{name}}} in the sweep command")


def _text(value):
    return value if isinstance(value, str) else json.dumps(value)
