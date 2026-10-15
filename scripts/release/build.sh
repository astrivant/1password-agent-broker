#!/usr/bin/env bash
# Build sibling Python distributions from one reviewed version and immutable workspace.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
root="$PWD"
version="$(poetry -C pkg/python/broker version --short)"

# Each manifest owns its source root; build from that directory for correct sdist/wheel discovery.
for package in broker_sdk broker; do
    (
        cd "pkg/python/$package"
        test "$(poetry version --short)" = "$version"
        poetry build --output "$root/dist"
    )
done
