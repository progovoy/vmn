#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

docker build --network=host -t vmn_tester:${1}_${2} --build-arg distro_var=${2} -f ${CUR_DIR}/vmn_tester_${1}_dockerfile ${CUR_DIR}
