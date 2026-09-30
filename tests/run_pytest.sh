#!/bin/bash
CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

set -o pipefail

usage()
{
cat << EOF
    Usage: run_pytest.sh [--suite core|exp (the default is core)]
           [--color] [--base_log_dir (the default is /tmp)]
           [--specific_test <test_name>]
           [--skip_test <test_name>]
           [--module_name <module_name> (the default is the suite's tests directory)]
           [--ci_coverage] (turns on pytest coverage for codecov, pytest-coverage should be installed)
           [-h or --help for this usage message]
    Suites: core = vmn alone (tests/, vmn's source root only);
            exp  = vmn-exp (packages/vmn-exp/tests/, all three source roots).
    Default values: --base_log_dir='/tmp'
EOF
}

color='no'
ci_coverage='no'
base_log_dir='/tmp/'
specific_test='none'
skip_test='none'
suite='core'
module_name=''
html_report_suffix='all'

while [ "$1" != "" ]; do
    case $1 in
        --suite )          shift
                           suite=$1
                           ;;
        --base_log_dir )   shift
                           base_log_dir=$1
                           ;;
        --module_name )    shift
                           module_name=$1
                           ;;
        --specific_test )   shift
                           specific_test=$1
			   html_report_suffix=${specific_test}
                           ;;
        --skip_test     )  shift
                           skip_test=$1
                           ;;
        --color )          color='yes'
                           ;;
        --ci_coverage )    ci_coverage='yes'
                           ;;
        -h | --help )      usage
                           exit 0
                           ;;
        * )                usage
                           exit 1
    esac
    shift
done

REPO_ROOT="$(cd "${CUR_DIR}/.." && pwd)"

case ${suite} in
    core ) SUITE_DIR=${CUR_DIR}
           SRC_PATH=${REPO_ROOT}/packages/vmn/src
           COV_PACKAGES='--cov=version_stamp'
           ;;
    exp )  SUITE_DIR=${REPO_ROOT}/packages/vmn-exp/tests
           SRC_PATH=${REPO_ROOT}/packages/vmn/src:${REPO_ROOT}/packages/vmn-exp-sdk/src:${REPO_ROOT}/packages/vmn-exp/src
           COV_PACKAGES='--cov=vmn_exp'
           ;;
    * )    usage
           exit 1
esac
module_name=${module_name:-${SUITE_DIR}}

COLOR=''
if [ ${color} = 'yes' ]; then
	COLOR='--color=yes'
fi

COVERAGE=''
if [ ${ci_coverage} = 'yes' ]; then
        COVERAGE="--cov-report term --cov-report html ${COV_PACKAGES}"
fi

K_EXPR=''
if [ "${specific_test}" != 'none' ]; then
	K_EXPR="(${specific_test})"
fi
if [ "${skip_test}" != 'none' ]; then
	K_EXPR="${K_EXPR:+${K_EXPR} and }not (${skip_test})"
fi
K_ARGS=()
if [ -n "${K_EXPR}" ]; then
	K_ARGS=(-k "${K_EXPR}")
fi
html_report_suffix=${suite}_${html_report_suffix//[^A-Za-z0-9_.-]/_}

DATE=$(date +%Y-%m-%d_%H-%M-%S)
OUT_PATH=${base_log_dir}

rm -rf ${REPO_ROOT}/version_stamp/__pycache__
# macOS caches .pyc files outside __pycache__, under a tree mirroring the
# source's absolute path. A stale cache from a build (where version.py
# transiently holds the real version) breaks tests: version.py keeps the same
# size across stamp/revert, so if both writes land in the same second Python's
# (mtime, size) check accepts the stale bytecode.
rm -rf "${HOME}/Library/Caches/com.apple.python${REPO_ROOT}"

PYTHON=${PYTHON:-python3}
if ! ${PYTHON} -c 'import coverage, pytest' 2>/dev/null; then
	echo "${PYTHON} cannot import coverage/pytest. Activate the test venv" \
	     "(or set PYTHON=<interpreter>) and install the suite's test_requirements.txt." >&2
	exit 1
fi

echo "Will run the ${suite} suite:"
export PYTHONPATH=${SRC_PATH}
cmd='${PYTHON} -m coverage run -m pytest  -n 29 --html=report_${html_report_suffix}.html --self-contained-html -vv ${COVERAGE} ${COLOR} "${K_ARGS[@]}" ${module_name} | tee ${OUT_PATH}/tests_output.log'

echo "${cmd}"
eval "${cmd}"

RET_CODE=$?

exit ${RET_CODE}
