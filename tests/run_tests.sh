#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${CUR_DIR}/.." && pwd)"

PYTHON_VERSIONS="${VMN_TEST_PYTHON_VERSIONS:-3.8 3.9 3.10 3.11 3.12}"

for pyver in ${PYTHON_VERSIONS}; do
    echo "============================================="
    echo "  Testing with Python ${pyver}"
    echo "============================================="

    ${CUR_DIR}/build_vmn_python_tester.sh ${pyver} || exit 1

    docker run --init -t \
        -v ${REPO_ROOT}:${REPO_ROOT} \
        vmn_tester:python_${pyver} \
        bash -c "pip install --no-cache-dir ${REPO_ROOT} && ${CUR_DIR}/run_pytest.sh $*" || exit 1

    echo "  Python ${pyver}: PASSED"
    echo ""
done

exit 0
