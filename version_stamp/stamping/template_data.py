#!/usr/bin/env python3
"""Jinja2 template generation utilities."""
import os
import subprocess
from pprint import pformat

import jinja2
import yaml

from version_stamp.core.logging import VMN_LOGGER


def create_data_dict_for_jinja2(
    start_tag_name, end_tag_name, repo_path, ver_info, custom_values_path
):
    tmplt_value = {}
    tmplt_value.update(ver_info["stamping"]["app"])

    if custom_values_path is not None:
        with open(custom_values_path, "r") as f:
            ret = yaml.safe_load(f)
            tmplt_value.update(ret)

    if "root_app" in ver_info["stamping"]:
        for key, v in ver_info["stamping"]["root_app"].items():
            tmplt_value[f"root_{key}"] = v

    toml_cliff_conf_param = ""
    if "release_notes_conf_path" in tmplt_value:
        toml_cliff_conf_param = f"-c {tmplt_value['release_notes_conf_path']}"

    command = f"git-cliff {toml_cliff_conf_param} {start_tag_name}..{end_tag_name} -r {repo_path}"
    try:
        result = subprocess.run(
            command.split(), check=True, text=True, capture_output=True
        )
        changelog_output = result.stdout
    except subprocess.CalledProcessError as e:
        VMN_LOGGER.error(e.stderr)
        raise e

    tmplt_value["release_notes"] = changelog_output

    return tmplt_value


def gen_jinja2_template_from_data(data, jinja_template_path, output_path):
    env = jinja2.Environment(keep_trailing_newline=True)

    with open(jinja_template_path) as file_:
        template_content = file_.read()

    template = env.from_string(template_content)

    VMN_LOGGER.debug(
        f"Possible keywords for your Jinja template:\n" f"{pformat(data)}"
    )
    out = template.render(data)

    if os.path.exists(output_path):
        with open(output_path) as file_:
            current_out_content = file_.read()

            if current_out_content == out:
                return 0

    with open(output_path, "w") as f:
        f.write(out)
