#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

${CUR_DIR}/build_vmn_tester.sh ubuntu xenial || exit 1
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_xenial ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_xenial ${CUR_DIR}/run_pytest.sh || exit 1

${CUR_DIR}/build_vmn_tester.sh ubuntu bionic || exit 1
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_bionic ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_bionic ${CUR_DIR}/run_pytest.sh || exit 1

${CUR_DIR}/build_vmn_tester.sh ubuntu focal || exit 1
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_focal ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_focal ${CUR_DIR}/run_pytest.sh || exit 1

${CUR_DIR}/run_pytest.sh || exit 1

exit 0
