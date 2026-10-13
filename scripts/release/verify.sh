#!/usr/bin/env bash
# Verify the public release independently of whether its publishing job ran.
# GitHub_release_environment::env EXPECTED_RELEASE_KEY_FINGERPRINT::sha256 -> ret::exit_code
set -euo pipefail
: "${GITHUB_REF_NAME:?Release tag required}"
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_SHA:?Expected source revision required}"
: "${EXPECTED_RELEASE_KEY_FINGERPRINT:?Independent signing-key fingerprint required}"
[[ $(gh release view "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft) == false ]]
checked=$(mktemp -d)
trap 'rm -rf "$checked"' EXIT
gh release download "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --dir "$checked"
fingerprint=$(openssl pkey -pubin -in "$checked/cosign.pub" -outform DER 2>/dev/null | openssl dgst -sha256)
[[ ${fingerprint##* } == "$EXPECTED_RELEASE_KEY_FINGERPRINT" ]]
cosign verify-blob --insecure-ignore-tlog --key "$checked/cosign.pub" \
    --bundle "$checked/SHA256SUMS.sigstore.json" "$checked/SHA256SUMS"
version=${GITHUB_REF_NAME#v}
required=("1password_agent_broker-$version-py3-none-any.whl" "1password_agent_broker-$version.tar.gz"
    "1password-agent-broker-$version.tgz" SOURCE.txt SHA256SUMS SHA256SUMS.sigstore.json cosign.pub fingerprint.txt)
files=("$checked"/*)
[[ ${#files[@]} -eq ${#required[@]} ]]
for name in "${required[@]}"; do
    test -f "$checked/$name"
done
printf 'Repository: %s\nTag: %s\nSource commit: %s\n' "$GITHUB_REPOSITORY" "$GITHUB_REF_NAME" "$GITHUB_SHA" |
    cmp - "$checked/SOURCE.txt"
(
    cd "$checked"
    sha256sum --check SHA256SUMS
    sha256sum "./${required[0]}" "./${required[1]}" "./${required[2]}" SOURCE.txt >expected-checksums
    cmp expected-checksums SHA256SUMS
)
