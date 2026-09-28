#!/bin/bash
# Release every package with a patch bump: vmn first (vmn-exp depends on it),
# then vmn-exp and vmn-exp-sdk together. Each release stamps (vmn writes the
# version into the pyproject.toml files, commits, tags and pushes), builds and
# uploads (see `make upload` for which ~/.pypirc section each file uses).
set -euo pipefail
cd "$(dirname "$0")"

if [ -n "$(git status --porcelain)" ]; then
    echo "release.sh: the working tree has uncommitted changes" >&2
    exit 1
fi
git fetch --tags --quiet

release() {
    local app=$1 mode=patch
    # The first vmn_exp release must skip 0.0.1: the PyPI placeholders hold it.
    if [ -z "$(git tag -l "${app}_*")" ]; then
        mode=minor
    fi
    vmn stamp -r "${mode}" "${app}"
    make _build NAME="${app}"
    make upload NAME="${app}"
}

release vmn
release vmn_exp
