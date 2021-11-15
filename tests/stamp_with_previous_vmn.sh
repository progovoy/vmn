#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

cd /test_repo

git config user.email "you@example.com"
git config user.name "Your Name"

vmn init
vmn init-app app1
vmn stamp -r patch app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp -r patch app1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin

vmn stamp -r patch root_app/service1
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp -r patch root_app/service2
echo a >> a.txt ; git add a.txt ; git commit -m "txt" ; git push origin
vmn stamp -r patch app1
