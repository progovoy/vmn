#!/bin/bash
# Build an app's packages at the version `vmn show <app>` reports for HEAD, so
# a `vmn release` (a tag on the stamped rc commit) builds the release, not the
# rc that `vmn stamp` wrote into the files. The version is written into the
# files the app's version_backends own only for the build, then restored.
# Usage: build_dist.sh vmn|vmn_exp <dist-dir>
set -euo pipefail
cd "$(dirname "$0")"

name=$1 dist=$2
if [ "${name}" = vmn_exp ]; then
    packages=(packages/vmn-exp-sdk packages/vmn-exp)
    files=(packages/vmn-exp-sdk/pyproject.toml packages/vmn-exp/pyproject.toml)
else
    packages=(packages/vmn)
    files=(packages/vmn/pyproject.toml packages/vmn/src/version_stamp/version.py)
fi

version=$(vmn show "${name}")
if [[ "${version}" == *$'\n'* || -z "${version}" ]]; then
    echo "build_dist.sh: HEAD is not a stamped version of ${name}:" >&2
    echo "${version}" >&2
    exit 1
fi

backup=$(mktemp -d)
restore() {
    for f in "${files[@]}"; do cp "${backup}/${f//\//_}" "${f}"; done
    rm -rf "${backup}"
}
for f in "${files[@]}"; do cp "${f}" "${backup}/${f//\//_}"; done
trap restore EXIT

for f in "${files[@]}"; do
    sed -i.bak -E \
        -e "s/^(_?version = \")[^\"]*(\")/\1${version}\2/" \
        -e "s/(\"vmn-exp-sdk==)[^\"]*(\")/\1${version}\2/" "${f}"
    rm -f "${f}.bak"
done

echo "Building ${name} ${version}"
for pkg in "${packages[@]}"; do uv build --out-dir "${dist}" "${pkg}"; done
