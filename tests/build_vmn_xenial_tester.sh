#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

docker build --network=host -t vmn_tester:ubuntu_xenial -f ${CUR_DIR}/vmn_tester_ubuntu_xenial_dockerfile ${CUR_DIR}

