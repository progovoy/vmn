#!/usr/bin/env bash
# vmn demo: microservices under a root app + multi-repo restore.
# Uses only throwaway local repos in a temp dir (local bare repos as remotes).
set -euo pipefail

DEMO=$(mktemp -d /tmp/vmn-demo.XXXXXX)
cd "$DEMO"
step() { printf '\n== %s\n' "$*"; }
run()  { printf '$ %s\n' "$*"; "$@"; }

export GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.com
export GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.com
export GIT_CONFIG_GLOBAL=/dev/null   # ignore your personal git config

step "Install vmn into a temp venv"
python3 -m venv venv >/dev/null
./venv/bin/pip install -q vmn
export PATH="$DEMO/venv/bin:$PATH"
run vmn --version

step "Create local bare 'remotes' and clones: platform (services) and lib_core (a dependency)"
mkdir remotes work
for r in platform lib_core; do
  git init -q --bare -b main "remotes/$r.git"
  git clone -q "$DEMO/remotes/$r.git" "work/$r" 2>/dev/null
  (cd "work/$r" && git checkout -q -b main && echo "# $r" > README.md \
     && git add . && git commit -qm "init $r" && git push -q -u origin main)
done
cd work/platform
mkdir auth billing; echo v1 > auth/app.txt; echo v1 > billing/app.txt
git add . && git commit -qm "feat: add auth and billing" && git push -q

step "(a) Stamp two services independently under the root app 'platform'"
run vmn stamp -r patch platform/auth
run vmn stamp -r minor platform/billing
run vmn show platform/auth
run vmn show platform/billing
run vmn show --root platform

step "(b) Give platform/auth a dependency repo (../lib_core) and stamp"
cat > .vmn/platform/auth/conf.yml <<'YML'
conf:
  deps:
    ../:
      lib_core:
        vcs_type: git
YML
git add .vmn && git commit -qm "chore: auth depends on lib_core" && git push -q
echo v2 > auth/app.txt; git commit -qam "feat: auth v2" && git push -q
run vmn stamp -r minor platform/auth
AUTH_VER=$(vmn show platform/auth)
ROOT_VER=$(vmn show --root platform)
LIB_AT_STAMP=$(git -C ../lib_core rev-parse --short HEAD)
echo "auth=$AUTH_VER root=$ROOT_VER lib_core@$LIB_AT_STAMP"

step "The release record: an annotated tag with YAML"
run git cat-file -p "platform-auth_$AUTH_VER"

step "Keep working: new commits in both repos"
(cd ../lib_core && echo change >> README.md && git commit -qam "lib change" && git push -q)
echo v3 > auth/app.txt; git commit -qam "wip: auth v3" && git push -q
echo "auth/app.txt=$(cat auth/app.txt)  lib_core@$(git -C ../lib_core rev-parse --short HEAD)"

step "Restore auth $AUTH_VER: app repo and lib_core go back"
run vmn goto -v "$AUTH_VER" platform/auth
echo "auth/app.txt=$(cat auth/app.txt)  lib_core@$(git -C ../lib_core rev-parse --short HEAD) (stamped at $LIB_AT_STAMP)"

step "Back to the branch tip, then restore root version $ROOT_VER"
run vmn goto platform/auth
echo "auth/app.txt=$(cat auth/app.txt)"
run vmn goto --root -v "$ROOT_VER" platform
echo "auth/app.txt=$(cat auth/app.txt)  lib_core@$(git -C ../lib_core rev-parse --short HEAD)"
run vmn show --root platform

step "Done. Everything lives in $DEMO (delete it when finished)."
