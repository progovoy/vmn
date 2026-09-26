#!/bin/bash
# Runs inside a clean-room python:X container. $1 is the pip install target.
#
# Nothing is pre-installed, so this exercises the dependency resolution a real
# user hits — which tests/run_tests.sh cannot, because its image installs every
# runtime dependency before vmn itself.

set -e

TARGET="$1"

echo "--- pip install ${TARGET}"
pip install --no-cache-dir --disable-pip-version-check "${TARGET}"

git config --global user.email "smoke@example.com"
git config --global user.name "smoke"
git config --global init.defaultBranch master

# vmn requires a remote to stamp, so give the smoke repo a local bare one.
git init -q --bare /tmp/smoke_remote

# Never run from /src: imports must resolve to the install, not the checkout.
git clone -q /tmp/smoke_remote /tmp/smoke
cd /tmp/smoke
echo hello > f.txt
git add f.txt
git commit -qm "init"
git push -q origin master

echo "--- console scripts on PATH"
command -v vmn
command -v vmn-argcomplete-tcsh

echo "--- vmn --version"
vmn --version

echo "--- installed distribution is complete"
python /src/tests/check_subpackages.py

echo "--- end-to-end stamp"
vmn stamp -r patch smoke_app
actual="$(vmn show smoke_app)"
if [ "${actual}" != "0.0.1" ]; then
    echo "expected 'vmn show smoke_app' to print 0.0.1, got '${actual}'" >&2
    exit 1
fi

echo "--- OK"
