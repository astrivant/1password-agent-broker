#!/usr/bin/env bash
# Install the exact wheel retrieved from PyPI outside the checkout and run its synthetic demo.
# RELEASE_VERSION::string -> ret::exit_code
set -euo pipefail
: "${RELEASE_VERSION:?Published version required}"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
export PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple PIP_EXTRA_INDEX_URL=

# Compare registry metadata before accepting an index download, then compare the downloaded bytes too.
python3 scripts/release/check_pypi.py --version "$RELEASE_VERSION" --directory pypi-dist
python3 -m venv "$scratch/venv"
"$scratch/venv/bin/python" -m pip download --no-cache-dir --no-deps --only-binary=:all: \
    --dest "$scratch" "1password-agent-broker==$RELEASE_VERSION"
wheel="1password_agent_broker-$RELEASE_VERSION-py3-none-any.whl"
cmp "pypi-dist/$wheel" "$scratch/$wheel"
"$scratch/venv/bin/python" -m pip install "$scratch/$wheel"
(
    cd "$scratch"
    "$scratch/venv/bin/agent-broker" demo
)
