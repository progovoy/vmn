#!/bin/bash
# Clean-room install matrix: does `pip install vmn` actually work for a user on
# every supported Python?
#
# tests/run_tests.sh cannot answer that. Its image pre-installs every runtime
# dependency, so by the time it runs `pip install <repo>` the requirements are
# already satisfied and pip never resolves install_requires from scratch. Here
# the base image is stock python:X with nothing pre-installed, and vmn is
# installed from the built wheel and sdist — the same artifacts PyPI serves.

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${CUR_DIR}/.." && pwd)"

PYTHON_VERSIONS="${VMN_TEST_PYTHON_VERSIONS:-3.8 3.9 3.10 3.11 3.12}"
EXTRAS="${VMN_TEST_EXTRAS:-ui s3 changelog}"
BUILD_PYTHON="${VMN_TEST_BUILD_PYTHON:-3.11}"

DIST_DIR="$(mktemp -d)"
trap 'rm -rf "${DIST_DIR}"' EXIT

FAILURES=()

extra_check()
{
    case "$1" in
        ui)        echo "python -c 'import fastapi, uvicorn'" ;;
        s3)        echo "python -c 'import boto3'" ;;
        changelog) echo "git-cliff --version" ;;
        *)         echo "true" ;;
    esac
}

run_case()
{
    local pyver="$1" label="$2"
    shift 2

    local log="${DIST_DIR}/py${pyver}-${label}.log"
    echo "  [${pyver}] ${label} ... "

    if docker run --rm --network=host \
        -v "${REPO_ROOT}:/src:ro" \
        -v "${DIST_DIR}:/dist:ro" \
        "python:${pyver}" \
        "$@" > "${log}" 2>&1
    then
        echo "  [${pyver}] ${label}: PASSED"
    else
        echo "  [${pyver}] ${label}: FAILED"
        echo "----- last 40 lines of ${log} -----"
        tail -40 "${log}"
        echo "-----------------------------------"
        FAILURES+=("${pyver}/${label}")
    fi
}

echo "============================================="
echo "  Building sdist + wheel (python ${BUILD_PYTHON})"
echo "============================================="

docker run --rm --network=host \
    -v "${REPO_ROOT}:/src:ro" \
    -v "${DIST_DIR}:/dist" \
    "python:${BUILD_PYTHON}" \
    bash -c '
        set -e
        pip install --no-cache-dir --disable-pip-version-check -q build
        mkdir -p /tmp/src
        tar -C /src \
            --exclude=./venv --exclude=./.git --exclude=./dist \
            --exclude=./build --exclude=./node_modules \
            -cf - . | tar -C /tmp/src -xf -
        cd /tmp/src
        python -m build --outdir /dist
    ' || { echo "Failed to build distributions"; exit 1; }

WHEEL="$(cd "${DIST_DIR}" && ls ./*.whl 2>/dev/null | head -1)"
SDIST="$(cd "${DIST_DIR}" && ls ./*.tar.gz 2>/dev/null | head -1)"

if [ -z "${WHEEL}" ] || [ -z "${SDIST}" ]; then
    echo "Build produced no wheel and/or sdist"
    exit 1
fi

echo "  wheel: ${WHEEL}"
echo "  sdist: ${SDIST}"
echo ""

for pyver in ${PYTHON_VERSIONS}; do
    echo "============================================="
    echo "  Clean-room install on Python ${pyver}"
    echo "============================================="

    run_case "${pyver}" "wheel" bash /src/tests/install_smoke.sh "/dist/${WHEEL}"
    run_case "${pyver}" "sdist" bash /src/tests/install_smoke.sh "/dist/${SDIST}"

    for extra in ${EXTRAS}; do
        run_case "${pyver}" "extra:${extra}" bash -c \
            "pip install --no-cache-dir --disable-pip-version-check '/dist/${WHEEL}[${extra}]' && $(extra_check "${extra}")"
    done

    echo ""
done

echo "============================================="
if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "  All clean-room installs PASSED"
    echo "============================================="
    exit 0
fi

echo "  FAILED: ${#FAILURES[@]} case(s)"
for failure in "${FAILURES[@]}"; do
    echo "    - ${failure}"
done
echo "============================================="
exit 1
