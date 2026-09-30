#!/bin/bash
# Runs run_pytest.sh (same options, incl. --suite core|exp) in Docker per Python
# version. The core suite gets vmn only installed; the exp suite all three.

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${CUR_DIR}/.." && pwd)"

PYTHON_VERSIONS="${VMN_TEST_PYTHON_VERSIONS:-3.8 3.9 3.10 3.11 3.12}"

suite='core'
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    if [ "${args[i]}" = '--suite' ]; then
        suite=${args[i + 1]}
    fi
done

PACKAGES="${REPO_ROOT}/packages/vmn"
if [ "${suite}" = 'exp' ]; then
    PACKAGES="${PACKAGES} ${REPO_ROOT}/packages/vmn-exp-sdk \"${REPO_ROOT}/packages/vmn-exp[ui]\""
fi

for pyver in ${PYTHON_VERSIONS}; do
    echo "============================================="
    echo "  Testing with Python ${pyver} (${suite} suite)"
    echo "============================================="

    ${CUR_DIR}/build_vmn_python_tester.sh ${pyver} || exit 1

    docker run --init -t \
        -v ${REPO_ROOT}:${REPO_ROOT} \
        vmn_tester:python_${pyver} \
        bash -c "pip install --no-cache-dir ${PACKAGES} && ${CUR_DIR}/run_pytest.sh $*" || exit 1

    echo "  Python ${pyver}: PASSED"
    echo ""
done

exit 0
