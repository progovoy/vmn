#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
apt update
yes | apt intall python3-venv
python3 -m venv ${CUR_DIR}/venv
source ${CUR_DIR}/venv/bin/activate
yes | apt intall python3-pip
pip install -r ${CUR_DIR}/tests/requirements.txt
pip install -r ${CUR_DIR}/tests/test_requirements.txt

