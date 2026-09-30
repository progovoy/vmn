#!/bin/bash
# Run the vmn-exp suite: tests/run_pytest.sh --suite exp, same options.
CUR_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "${CUR_DIR}/../../../tests/run_pytest.sh" --suite exp "$@"
