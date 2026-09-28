#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -m venv ${CUR_DIR}/venv
source ${CUR_DIR}/venv/bin/activate
pip install -r ${CUR_DIR}/tests/requirements.txt
pip install -r ${CUR_DIR}/tests/test_requirements.txt
pip install -e ${CUR_DIR}/packages/vmn -e ${CUR_DIR}/packages/vmn-exp-sdk -e "${CUR_DIR}/packages/vmn-exp[ui]"
