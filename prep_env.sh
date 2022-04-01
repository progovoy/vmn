#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -m venv ${CUR_DIR}/venv
source ${CUR_DIR}/venv/bin/activate
pip install -r ${CUR_DIR}/tests/requirements.txt
pip install -r ${CUR_DIR}/tests/test_requirements.txt

