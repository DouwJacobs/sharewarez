#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(python3 "${repo_root}/scripts/version.py" current)"
repository="${IMAGE_REPOSITORY:-douwjacobs/gamelibrary}"

docker build \
  --build-arg "APP_VERSION=${version}" \
  --label "org.opencontainers.image.revision=$(git -C "${repo_root}" rev-parse HEAD)" \
  --tag "${repository}:${version}" \
  --tag "${repository}:latest" \
  "${repo_root}"

echo "Built ${repository}:${version} and ${repository}:latest"
