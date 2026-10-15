#!/usr/bin/env bash
# Verify the public release independently of whether its publishing job ran.
# GitHub_release_environment::env EXPECTED_RELEASE_KEY_FINGERPRINT::sha256 python_destination?::path -> ret::exit_code
set -euo pipefail
: "${GITHUB_REF_NAME:?Release tag required}"
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_SHA:?Expected source revision required}"
: "${EXPECTED_RELEASE_KEY_FINGERPRINT:?Independent signing-key fingerprint required}"
[ "$(gh release view "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft)" = false ]
checked="$(mktemp -d)"
# Remove only this invocation's disposable verification directory on every exit.
# -> ret::exit_code
cleanup() {
    rm -rf -- "$checked"
}
trap cleanup EXIT
gh release download "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --dir "$checked"

# Establish trust independently before accepting the public key shipped alongside the artifacts.
fingerprint="$(openssl pkey -pubin -in "$checked/cosign.pub" -outform DER 2>/dev/null | openssl dgst -sha256)"
[ "${fingerprint##* }" = "$EXPECTED_RELEASE_KEY_FINGERPRINT" ]
cosign verify-blob --insecure-ignore-tlog --key "$checked/cosign.pub" \
    --bundle "$checked/SHA256SUMS.sigstore.json" "$checked/SHA256SUMS"
version=${GITHUB_REF_NAME#v}
python_files=("1password_agent_broker-$version-py3-none-any.whl" "1password_agent_broker-$version.tar.gz")
metadata=(SOURCE.txt)
if [ -f "$checked/PACKAGES.txt" ]; then
    # The marker is authenticated below and may name only the reviewed package set.
    printf '%s\n' '1password-agent-broker' '1password-agent-broker-sdk' | cmp - "$checked/PACKAGES.txt"
    python_files+=("1password_agent_broker_sdk-$version-py3-none-any.whl" "1password_agent_broker_sdk-$version.tar.gz")
    metadata+=(PACKAGES.txt)
fi
required=("${python_files[@]}" "1password-agent-broker-$version.tgz" "${metadata[@]}"
    SHA256SUMS SHA256SUMS.sigstore.json cosign.pub fingerprint.txt)
files=("$checked"/*)
[ "${#files[@]}" -eq "${#required[@]}" ]
for name in "${required[@]}"; do
    test -f "$checked/$name"
done
printf 'Repository: %s\nTag: %s\nSource commit: %s\n' "$GITHUB_REPOSITORY" "$GITHUB_REF_NAME" "$GITHUB_SHA" |
    cmp - "$checked/SOURCE.txt"
(
    cd "$checked"
    sha256sum --check SHA256SUMS

    # Reconstruct exact manifest membership to reject omitted payloads or unexpected signed entries.
    sha256sum ./*.whl ./*.tar.gz ./*.tgz "${metadata[@]}" >expected-checksums
    cmp expected-checksums SHA256SUMS
)

# Export only authenticated Python bytes to a new directory; never mix them with prior builds.
if [ "$#" -gt 0 ]; then
    [ "$#" -eq 1 ]
    mkdir "$1"
    for name in "${python_files[@]}"; do
        cp "$checked/$name" "$1/"
    done
fi
