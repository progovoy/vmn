#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "${CUR_DIR}")"

# Build from repo root to access pyproject.toml and version_stamp
docker build --network=host -t vmn_tester:ubuntu_xenial -f ${CUR_DIR}/vmn_tester_ubuntu_xenial_dockerfile ${REPO_DIR}
