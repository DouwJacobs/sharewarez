#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m piptools compile --strip-extras requirements.in --output-file requirements.txt
"$PYTHON_BIN" -m piptools compile --strip-extras requirements-dev.in --output-file requirements-dev.txt
