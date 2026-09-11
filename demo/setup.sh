#!/usr/bin/env bash
# Builds a throwaway multi-repo workspace for the README demo.
#
#   demo/setup.sh [workspace_dir]     # default: /tmp/vmn-demo
#
# Layout after setup (each repo has its own bare "remote"):
#   <workspace>/remotes/{shop,lib_core,service_api}.git
#   <workspace>/work/{shop,lib_core,service_api}
#
# `shop` is the application; lib_core and service_api are its dependency repos.
set -euo pipefail

WS="${1:-/tmp/vmn-demo}"
rm -rf "${WS}"
mkdir -p "${WS}/remotes" "${WS}/work"

export GIT_AUTHOR_NAME="demo" GIT_COMMITTER_NAME="demo"
export GIT_AUTHOR_EMAIL="demo@example.com" GIT_COMMITTER_EMAIL="demo@example.com"

make_repo() {
    local name="$1" file="$2" content="$3"
    git init -q --bare "${WS}/remotes/${name}.git"
    git clone -q "${WS}/remotes/${name}.git" "${WS}/work/${name}"
    (
        cd "${WS}/work/${name}"
        git checkout -q -b main
        echo "${content}" > "${file}"
        git add "${file}"
        git commit -q -m "chore: initial ${name}"
        git push -q -u origin main
    )
}

make_repo lib_core    core.py    'VERSION = "fast path off"'
make_repo service_api api.py     'ROUTES = ["/v1/orders"]'
make_repo shop        shop.py    'import core, api'

(cd "${WS}/work/shop" && vmn init >/dev/null && vmn init-app shop >/dev/null)
cat > "${WS}/work/shop/.vmn/shop/conf.yml" <<'YAML'
conf:
  deps:
    ../:
      lib_core:
        vcs_type: git
      service_api:
        vcs_type: git
YAML
(
    cd "${WS}/work/shop"
    git add .vmn
    git commit -q -m "chore: track lib_core and service_api with vmn"
    git push -q
)

echo "Demo workspace ready: ${WS}/work/shop"
