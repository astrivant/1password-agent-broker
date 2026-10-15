#!/usr/bin/env bash
# Verify signed chart/Python attachments and fail-closed publication with a local GitHub stub.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
scratch="$(mktemp -d)"
# Remove this invocation's synthetic signing material and artifact workspace on every exit.
# -> ret::exit_code
cleanup() {
    rm -rf -- "$scratch"
}
trap cleanup EXIT
mkdir "$scratch/bin" "$scratch/dist" "$scratch/uploads"
# Reuse the same independently linted host stub for setup and release contract checks.
cp scripts/ci/fixtures/release-gh.sh "$scratch/bin/gh"
chmod +x "$scratch/bin/gh"
bash scripts/ci/checks/signing.sh
export GH_STUB_KEYS="$scratch/keys" GH_STUB_CALLS="$scratch/secret-calls"
PATH="$scratch/bin:$PATH" bash scripts/release/setup-signing.sh --repo synthetic/repository --key-dir "$GH_STUB_KEYS"
cp dist/*.whl dist/*.tar.gz dist/*.tgz "$scratch/dist/"
export COSIGN_PRIVATE_KEY COSIGN_PASSWORD
COSIGN_PRIVATE_KEY="$(cat "$scratch/keys/cosign.key")"
COSIGN_PASSWORD="$(cat "$scratch/keys/cosign.password")"
export GH_STUB_ASSETS="$scratch/uploads"
release_script="$PWD/scripts/release/publish.sh"
verify_script="$PWD/scripts/release/verify.sh"
# Require an unambiguous current build instead of silently selecting the first retained wheel.
shopt -s nullglob
wheels=(dist/1password_agent_broker-*.whl)
[ "${#wheels[@]}" -eq 1 ] || {
    echo 'Expected exactly one built runtime wheel' >&2
    exit 1
}
version=${wheels[0]#dist/1password_agent_broker-}
version=${version%-py3-none-any.whl}
(
    cd "$scratch"
    export GITHUB_REF_NAME="v$version" GITHUB_REPOSITORY=synthetic/repository GITHUB_SHA=synthetic-commit
    export PATH="$scratch/bin:$PATH"
    # A retained older build must be rejected before signing or creating a draft.
    touch dist/stale.whl
    if bash "$release_script"; then
        echo 'Stale build output was accepted' >&2
        exit 1
    fi
    test -z "$(ls -A "$GH_STUB_ASSETS")"
    rm dist/stale.whl

    # The right archive count is insufficient when a build belongs to another version.
    mv "dist/1password_agent_broker-$version-py3-none-any.whl" dist/incorrect-version.whl
    if bash "$release_script"; then
        echo 'Wrong-version build output was accepted' >&2
        exit 1
    fi
    test -z "$(ls -A "$GH_STUB_ASSETS")"
    mv dist/incorrect-version.whl "dist/1password_agent_broker-$version-py3-none-any.whl"
    bash "$release_script"
    test -f "$GH_STUB_ASSETS/published"
    fingerprint="$(openssl pkey -pubin -in "$GH_STUB_ASSETS/cosign.pub" -outform DER 2>/dev/null | openssl dgst -sha256)"
    EXPECTED_RELEASE_KEY_FINGERPRINT="${fingerprint##* }" bash "$verify_script" verified-python
    test "$(find verified-python -type f | wc -l | tr -d ' ')" = 4
    cmp "dist/1password_agent_broker-$version-py3-none-any.whl" "verified-python/1password_agent_broker-$version-py3-none-any.whl"
    cmp "dist/1password_agent_broker-$version.tar.gz" "verified-python/1password_agent_broker-$version.tar.gz"

    cmp "dist/1password_agent_broker_sdk-$version-py3-none-any.whl" "verified-python/1password_agent_broker_sdk-$version-py3-none-any.whl"
    cmp "dist/1password_agent_broker_sdk-$version.tar.gz" "verified-python/1password_agent_broker_sdk-$version.tar.gz"

    # Removing the package marker must fail even though the original manifest still verifies.
    mv "$GH_STUB_ASSETS/PACKAGES.txt" "$scratch/saved-packages"
    if EXPECTED_RELEASE_KEY_FINGERPRINT="${fingerprint##* }" bash "$verify_script"; then
        echo 'Missing signed package inventory was accepted' >&2
        exit 1
    fi
    mv "$scratch/saved-packages" "$GH_STUB_ASSETS/PACKAGES.txt"

    # A reused output directory must fail rather than carry files from another publication attempt.
    if EXPECTED_RELEASE_KEY_FINGERPRINT="${fingerprint##* }" bash "$verify_script" verified-python; then
        echo 'Existing Python publication directory was accepted' >&2
        exit 1
    fi

    # A valid bundled key is insufficient unless it matches the independently supplied trust anchor.
    if EXPECTED_RELEASE_KEY_FINGERPRINT=untrusted bash "$verify_script"; then
        echo 'Untrusted signing key was accepted' >&2
        exit 1
    fi
    if EXPECTED_RELEASE_KEY_FINGERPRINT=untrusted bash "$verify_script" untrusted-python; then
        echo 'Untrusted Python distribution export was accepted' >&2
        exit 1
    fi
    test ! -e untrusted-python
    rm "$GH_STUB_ASSETS/published"

    # Corruption must block the final publish action, not merely produce a diagnostic after publication.
    if GH_STUB_CORRUPT=1 bash "$release_script"; then
        echo 'Corrupted downloaded artifact was accepted' >&2
        exit 1
    fi
    test ! -e "$GH_STUB_ASSETS/published"
)
