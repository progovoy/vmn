"""CLI formatting helpers for experiment provenance output.

Used by ``vmn-exp show``, ``vmn-exp diff``, and ``vmn-exp compare``.
"""
import yaml

from vmn_exp.core.provenance import env_diff, inputs_diff, no_code_reason


# ---------------------------------------------------------------------------
# Env one-liner
# ---------------------------------------------------------------------------

def format_env_oneliner(env_summary):
    """Return a compact one-liner from an env *summary* dict.

    Example: ``"3.11.2, Linux/x86_64, torch=2.2.1, cuda=12.1"``

    *env_summary* is the ``env`` field from the run's metadata (the compact
    summary, not the full ``env.yml`` dict).
    """
    parts = []
    if env_summary.get("python"):
        parts.append(env_summary["python"])
    if env_summary.get("platform"):
        parts.append(env_summary["platform"])
    key_pkgs = env_summary.get("key_packages") or {}
    for pkg, ver in sorted(key_pkgs.items()):
        parts.append(f"{pkg}={ver}")
    cuda = env_summary.get("cuda") or {}
    if isinstance(cuda, dict) and cuda.get("torch_cuda"):
        parts.append(f"cuda={cuda['torch_cuda']}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Inputs block
# ---------------------------------------------------------------------------

def format_inputs_lines(inputs):
    """Return display lines for an inputs dict (name → {uri, digest, kind}).

    Each line is indented with two spaces and shows the name and its URI.
    """
    if not inputs:
        return []
    lines = []
    for name, info in sorted(inputs.items()):
        uri = (info or {}).get("uri") or ""
        kind = (info or {}).get("kind")
        digest = (info or {}).get("digest")
        line = f"  {name}: {uri}"
        extras = []
        if kind:
            extras.append(kind)
        if digest:
            extras.append(digest)
        if extras:
            line += f"  ({', '.join(extras)})"
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Provenance diff section (for exp diff / compare)
# ---------------------------------------------------------------------------

def _load_full_env(storage, app_name, verstr):
    """Load the full env dict from ``env.yml``; returns ``None`` on failure."""
    try:
        content = storage.load_file(app_name, verstr, "env.yml")
        if content is None:
            return None
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        return yaml.safe_load(content)
    except Exception:
        return None


def print_provenance_diff_section(storage, app_name, v1, meta1, v2, meta2, cap=30):
    """Print the env / packages / inputs diff section between two runs.

    Printed only when there is something to show.  Output is capped at
    *cap* change lines (+ one ``"... N more"`` trailer).
    """
    # Skip the storage round-trips when neither run captured an environment.
    if (meta1 or {}).get("env") or (meta2 or {}).get("env"):
        env1 = _load_full_env(storage, app_name, v1) or {}
        env2 = _load_full_env(storage, app_name, v2) or {}
    else:
        env1 = env2 = {}

    e_lines = env_diff(env1, env2, cap=cap)
    if e_lines:
        print("\nEnv/packages:")
        for ln in e_lines:
            print(f"  {ln}")

    inputs1 = (meta1.get("inputs") or {}) if isinstance(meta1, dict) else {}
    inputs2 = (meta2.get("inputs") or {}) if isinstance(meta2, dict) else {}
    i_lines = inputs_diff(inputs1, inputs2)
    if i_lines:
        print("\nInputs:")
        for ln in i_lines:
            print(f"  {ln}")


# ---------------------------------------------------------------------------
# No-code refusal helper
# ---------------------------------------------------------------------------

def refuse_no_code(meta, action="restore"):
    """Log an error and return 1 if *meta* is for a no-code run.

    Returns ``None`` when the run has a code snapshot (caller should proceed).
    """
    from version_stamp.api import VMN_LOGGER  # lazy; avoids circular at module level

    reason = no_code_reason(meta)
    if reason is None:
        return None
    VMN_LOGGER.error(
        f"Cannot {action}: {reason}. "
        "Check out the source commit manually to reproduce the code state."
    )
    return 1
