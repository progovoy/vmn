#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "${CUR_DIR}")"

# Build from repo root to access pyproject.toml and version_stamp
docker build --network=host -t vmn_tester:${1}_${2} --build-arg distro_var=${2} -f ${CUR_DIR}/vmn_tester_${1}_dockerfile ${REPO_DIR}
