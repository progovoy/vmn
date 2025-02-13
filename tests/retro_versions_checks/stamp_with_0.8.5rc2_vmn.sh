#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

cd /test_repo_0

git config --global --add safe.directory /test_repo_0

git config user.email "you@example.com"
git config user.name "Your Name"

vmn init
vmn init-app -v 2.3.1 app1
vmn stamp --orm patch --pr 148. app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp --orm patch --pr 636. app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp --orm patch --pr staging app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp --orm patch --pr staging app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
# result: 2.3.3-staging2

# last_known_version file:
#
# prerelease: staging
# prerelease_count:
#   '148.': 1
#   '636.': 1
#   staging: 2
# version_to_stamp_from: 2.3.2
