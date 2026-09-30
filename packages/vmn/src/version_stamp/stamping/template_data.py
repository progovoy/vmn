#!/usr/bin/env python3
"""Jinja2 template generation utilities."""
import os
import shutil
import subprocess
import sys
from pprint import pformat

import jinja2
import jinja2.meta
import yaml

from version_stamp.core.logging import VMN_LOGGER


def create_data_dict_for_jinja2(
    start_tag_name,
    end_tag_name,
    repo_path,
    ver_info,
    custom_values_path,
    jinja_template_path,
):
    tmplt_value = {}
    tmplt_value.update(ver_info["stamping"]["app"])

    if custom_values_path is not None:
        with open(custom_values_path) as f:
            ret = yaml.safe_load(f)
            tmplt_value.update(ret)

    if "root_app" in ver_info["stamping"]:
        for key, v in ver_info["stamping"]["root_app"].items():
            tmplt_value[f"root_{key}"] = v

    tmplt_value["release_notes"] = ""
    git_cliff = _git_cliff()
    # No start tag yet (init-app stamps the first version): nothing to note.
    if (
        git_cliff
        and _template_uses(jinja_template_path, "release_notes")
        and _ref_exists(repo_path, start_tag_name)
    ):
        tmplt_value["release_notes"] = _release_notes(
            git_cliff,
            f"{start_tag_name}..{end_tag_name}",
            repo_path,
            tmplt_value.get("release_notes_conf_path"),
        )

    return tmplt_value


def _template_uses(jinja_template_path, name):
    with open(jinja_template_path) as f:
        source = f.read()
    env = jinja2.Environment()
    return name in jinja2.meta.find_undeclared_variables(env.parse(source))


def _git_cliff():
    """Prefer the git-cliff installed with vmn: pipx and non-activated venvs keep it off PATH."""
    bundled_dir = os.path.dirname(sys.executable)
    return shutil.which("git-cliff", path=bundled_dir) or shutil.which("git-cliff")


def _release_notes(git_cliff, tag_range, repo_path, conf_path):
    command = [git_cliff]
    if conf_path:
        command += ["-c", conf_path]
    command += [tag_range, "-r", repo_path]
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        VMN_LOGGER.warning(
            f"git-cliff failed, rendering empty release_notes:\n{e.stderr}"
        )
        return ""
    return result.stdout


def _ref_exists(repo_path, ref):
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
    )
    return result.returncode == 0


def gen_jinja2_template_from_data(data, jinja_template_path, output_path):
    env = jinja2.Environment(keep_trailing_newline=True)

    with open(jinja_template_path) as file_:
        template_content = file_.read()

    template = env.from_string(template_content)

    VMN_LOGGER.debug(f"Possible keywords for your Jinja template:\n" f"{pformat(data)}")
    out = template.render(data)

    if os.path.exists(output_path):
        with open(output_path) as file_:
            current_out_content = file_.read()

            if current_out_content == out:
                return 0

    with open(output_path, "w") as f:
        f.write(out)
