#!/bin/bash
# Release vmn-exp and vmn-exp-sdk together with a patch bump: stamp the vmn_exp
# app (vmn writes the version into both pyproject.toml files, commits, tags and
# pushes), build, and upload (see `make upload` for which ~/.pypirc section each
# file uses). vmn itself is released separately; vmn-exp needs vmn>0.10.2rc9.
set -euo pipefail
cd "$(dirname "$0")"

if [ -n "$(git status --porcelain)" ]; then
    echo "release_exp.sh: the working tree has uncommitted changes" >&2
    exit 1
fi
git fetch --tags --quiet

release() {
    local app=$1 mode=patch
    # The first release must skip 0.0.1: the PyPI placeholders hold it.
    if [ -z "$(git tag -l "${app}_*")" ]; then
        mode=minor
    fi
    vmn stamp -r "${mode}" "${app}"
    make _build NAME="${app}"
    make upload NAME="${app}"
}

release vmn_exp
