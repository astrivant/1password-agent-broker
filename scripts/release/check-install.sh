#!/usr/bin/env bash
# Install the exact wheel retrieved from PyPI outside the checkout and run its synthetic demo.
# RELEASE_VERSION::string -> ret::exit_code
set -euo pipefail
: "${RELEASE_VERSION:?Published version required}"
scratch="$(mktemp -d)"
# Remove only this invocation's registry verification environments.
# -> ret::exit_code
cleanup() {
    rm -rf -- "$scratch"
}
trap cleanup EXIT
export PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple PIP_EXTRA_INDEX_URL=

# Compare registry metadata before accepting an index download, then compare the downloaded bytes too.
python3 scripts/release/check_pypi.py --version "$RELEASE_VERSION" --directory pypi-dist
# New releases authenticate and install the SDK independently before the runtime.
if [ -f "pypi-dist/1password_agent_broker_sdk-$RELEASE_VERSION-py3-none-any.whl" ]; then
    python3 -m venv "$scratch/sdk"
    "$scratch/sdk/bin/python" -m pip download --no-cache-dir --no-deps --only-binary=:all: \
        --dest "$scratch" "1password-agent-broker-sdk==$RELEASE_VERSION"
    sdk_wheel="1password_agent_broker_sdk-$RELEASE_VERSION-py3-none-any.whl"
    cmp "pypi-dist/$sdk_wheel" "$scratch/$sdk_wheel"
    "$scratch/sdk/bin/python" -m pip install "$scratch/$sdk_wheel"
    root="$PWD"
    (
        cd "$scratch"
        "$scratch/sdk/bin/python" "$root/scripts/release/check_sdk.py"
    )
fi
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
