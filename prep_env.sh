#!/bin/bash

CUR_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if uv is available, otherwise fall back to pip
if command -v uv &> /dev/null; then
    echo "Using uv for environment setup"
    cd "${CUR_DIR}"
    uv sync --extra dev
else
    echo "uv not found, using pip"
    python3 -m venv "${CUR_DIR}/venv"
    source "${CUR_DIR}/venv/bin/activate"
    pip install -e ".[dev]"
fi
