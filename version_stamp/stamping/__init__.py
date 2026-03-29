#!/usr/bin/env python3
"""Stamping logic: version calculation, publishing, and template generation."""

from version_stamp.stamping.base import IVersionsStamper  # noqa: F401
from version_stamp.stamping.publisher import VersionControlStamper  # noqa: F401
from version_stamp.stamping.template_data import (  # noqa: F401
    create_data_dict_for_jinja2,
    gen_jinja2_template_from_data,
)
