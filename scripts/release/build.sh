#!/usr/bin/env bash
# Build both distributions from one reviewed version and immutable workspace.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
root="$PWD"
version="$(poetry version --short)"
(
    cd packages/sdk
    test "$(poetry version --short)" = "$version"
    poetry build --output "$root/dist"
)
poetry build
