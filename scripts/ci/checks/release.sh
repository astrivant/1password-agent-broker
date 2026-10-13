#!/usr/bin/env bash
# Verify signed chart/Python attachments and fail-closed publication with a local GitHub stub.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin" "$scratch/dist" "$scratch/uploads"
# This stub consumes secret input without persisting it or making network requests.
cat >"$scratch/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == secret && $2 == set ]]; then
    cat >/dev/null
elif [[ $1 == release && $2 == view ]]; then
    if [[ -e "$GH_STUB_ASSETS/published" ]]; then echo false; else exit 1; fi
elif [[ $1 == release && $2 == create ]]; then
    [[ " $* " == *" --draft "* ]]
    for argument in "$@"; do
        if [[ $argument == dist/* && $argument != */release-notes.md ]]; then
            cp "$argument" "$GH_STUB_ASSETS/"
        fi
    done
elif [[ $1 == release && $2 == download ]]; then
    while [[ $1 != --dir ]]; do shift; done
    for asset in "$GH_STUB_ASSETS/"*; do
        if [[ $(basename "$asset") != published ]]; then cp "$asset" "$2/"; fi
    done
    if [[ ${GH_STUB_CORRUPT:-0} == 1 ]]; then
        printf 'corrupted\n' >>"$2/SOURCE.txt"
    fi
elif [[ $1 == release && $2 == edit ]]; then
    [[ " $* " == *" --draft=false "* ]]
    touch "$GH_STUB_ASSETS/published"
else
    exit 2
fi
STUB
chmod +x "$scratch/bin/gh"
PATH="$scratch/bin:$PATH" bash scripts/release/setup-signing.sh synthetic/repository "$scratch/keys"
cp dist/*.whl dist/*.tar.gz dist/*.tgz "$scratch/dist/"
export COSIGN_PRIVATE_KEY
COSIGN_PRIVATE_KEY=$(cat "$scratch/keys/cosign.key")
export GH_STUB_ASSETS="$scratch/uploads"
release_script="$PWD/scripts/release/publish.sh"
verify_script="$PWD/scripts/release/verify.sh"
wheels=(dist/*.whl)
version=${wheels[0]#dist/1password_agent_broker-}
version=${version%-py3-none-any.whl}
(
    cd "$scratch"
    export GITHUB_REF_NAME="v$version" GITHUB_REPOSITORY=synthetic/repository GITHUB_SHA=synthetic-commit
    export PATH="$scratch/bin:$PATH"
    bash "$release_script"
    test -f "$GH_STUB_ASSETS/published"
    fingerprint=$(openssl pkey -pubin -in "$GH_STUB_ASSETS/cosign.pub" -outform DER 2>/dev/null | openssl dgst -sha256)
    EXPECTED_RELEASE_KEY_FINGERPRINT="${fingerprint##* }" bash "$verify_script"
    if EXPECTED_RELEASE_KEY_FINGERPRINT=untrusted bash "$verify_script"; then
        echo 'Untrusted signing key was accepted' >&2
        exit 1
    fi
    rm "$GH_STUB_ASSETS/published"
    if GH_STUB_CORRUPT=1 bash "$release_script"; then
        echo 'Corrupted downloaded artifact was accepted' >&2
        exit 1
    fi
    test ! -e "$GH_STUB_ASSETS/published"
)
