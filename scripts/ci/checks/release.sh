#!/usr/bin/env bash
# Verify key setup and signed release artifacts without touching GitHub resources.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin" "$scratch/dist"
# This stub consumes secret input without persisting it or making network requests.
cat >"$scratch/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == secret && $2 == set ]]; then
    cat >/dev/null
elif [[ $1 == release && $2 == create ]]; then
    echo 'Synthetic release request accepted by local test stub'
else
    exit 2
fi
STUB
chmod +x "$scratch/bin/gh"
PATH="$scratch/bin:$PATH" bash scripts/release/setup-signing.sh synthetic/repository "$scratch/keys"
cp dist/*.whl dist/*.tar.gz "$scratch/dist/"
export COSIGN_PRIVATE_KEY
COSIGN_PRIVATE_KEY=$(cat "$scratch/keys/cosign.key")
release_script="$PWD/scripts/release/publish.sh"
(
    cd "$scratch"
    GITHUB_REF_NAME=v0.1.0 GITHUB_REPOSITORY=synthetic/repository GITHUB_SHA=synthetic-commit \
        PATH="$scratch/bin:$PATH" bash "$release_script"
    cd dist
    shasum -a 256 --check verification/SHA256SUMS
)
