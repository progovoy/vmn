#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

PYTHON_VERSION=${1:-3.8}

docker build --network=host \
    -t vmn_tester:python_${PYTHON_VERSION} \
    --build-arg PYTHON_VERSION=${PYTHON_VERSION} \
    -f ${CUR_DIR}/vmn_tester_python_dockerfile \
    ${CUR_DIR}
