#!/usr/bin/env bash
# Exercise independent SDK and runtime installations outside the source checkout.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
root="$PWD"
scratch="$(mktemp -d)"
# Remove only isolated installation environments owned by this invocation.
# -> ret::exit_code
cleanup() {
    rm -rf -- "$scratch"
}
trap cleanup EXIT
python3 -m venv "$scratch/sdk"
"$scratch/sdk/bin/python" -m pip install "$root"/dist/1password_agent_broker_sdk-*.whl
(
    cd "$scratch"
    "$scratch/sdk/bin/python" "$root/scripts/release/check_sdk.py"
)
python3 -m venv "$scratch/server"
"$scratch/server/bin/python" -m pip install "$root"/dist/*.whl
(
    cd "$scratch"
    "$scratch/server/bin/agent-broker" demo
)

# Rebuild from only published source archives so sibling paths cannot hide missing inputs.
python3 -m pip wheel --no-deps --wheel-dir "$scratch/rebuilt" "$root"/dist/*.tar.gz
"$scratch/sdk/bin/python" -m pip install --force-reinstall --no-deps "$scratch"/rebuilt/1password_agent_broker_sdk-*.whl
"$scratch/server/bin/python" -m pip install --force-reinstall --no-deps "$scratch"/rebuilt/*.whl
(
    cd "$scratch"
    "$scratch/sdk/bin/python" "$root/scripts/release/check_sdk.py"
    "$scratch/server/bin/agent-broker" demo
)
