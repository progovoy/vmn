#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

docker build --build-arg GROUP_ID=$(id -g ${USER}) --build-arg USER_ID=$(id -u ${USER}) -t previous_vmn_stamper:latest -f ${CUR_DIR}/previous_vmn_stamper_dockerfile ${CUR_DIR}
