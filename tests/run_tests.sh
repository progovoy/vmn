#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

${CUR_DIR}/build_vmn_tester.sh ubuntu xenial
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_xenial ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_xenial ${CUR_DIR}/run_pytest.sh

${CUR_DIR}/build_vmn_tester.sh ubuntu bionic
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_bionic ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_bionic ${CUR_DIR}/run_pytest.sh

${CUR_DIR}/build_vmn_tester.sh ubuntu focal
echo "docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_focal ${CUR_DIR}/run_pytest.sh"
docker run -t -v ${CUR_DIR}/..:${CUR_DIR}/.. vmn_tester:ubuntu_focal ${CUR_DIR}/run_pytest.sh

${CUR_DIR}/run_pytest.sh
