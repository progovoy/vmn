#!/bin/bash
CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

set -o pipefail

usage()
{
cat << EOF
    Usage: run_pytest.sh [--color] [--base_log_dir (the default is /tmp)]
           [--specific_test <test_name>]
           [--skip_test <test_name>]
           [--module_name <module_name> (the default is just the current directory)]
           [--ci_coverage] (turns on pytest coverage for codecov, pytest-coverage should be installed)
           [-h or --help for this usage message]
    Default values: --base_log_dir='/tmp'
EOF
}

color='no'
ci_coverage='no'
base_log_dir='/tmp/'
specific_test='none'
skip_test='none'
module_name=${CUR_DIR}
html_report_suffix='all'

while [ "$1" != "" ]; do
    case $1 in
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


COLOR=''
if [ ${color} = 'yes' ]; then
	COLOR='--color=yes'
fi

COVERAGE=''
if [ ${ci_coverage} = 'yes' ]; then
        COVERAGE='--cov-report term --cov-report html --cov=vmn --cov=stamp_utils'
fi

SPECIFIC_TEST=''
if [ ${specific_test} != 'none' ]; then
	SPECIFIC_TEST="-k ${specific_test}"
fi

SKIP_TEST=''
if [ ${skip_test} != 'none' ]; then
	SKIP_TEST="-k not ${skip_test}"
fi

DATE=$(date +%Y-%m-%d_%H-%M-%S)
OUT_PATH=${base_log_dir}

rm -rf ${CUR_DIR}/../version_stamp/__pycache__

echo "Will run:"
PYTHONPATH=${CUR_DIR}:${CUR_DIR}../ \
cmd='coverage run -m pytest  -n 29 --html=report_${html_report_suffix}.html --self-contained-html -vv ${COVERAGE} ${COLOR} ${SPECIFIC_TEST} "${SKIP_TEST}" ${module_name} | tee ${OUT_PATH}/tests_output.log'

echo "${cmd}"
eval "${cmd}"

RET_CODE=$?

exit ${RET_CODE}

