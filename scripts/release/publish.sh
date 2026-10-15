#!/usr/bin/env bash
# Assemble a draft, verify downloaded bytes, then publish the checked source artifacts.
# environment::GitHub_Actions -> ret::exit_code
set -euo pipefail
umask 077
: "${GITHUB_REF_NAME:?Version tag required}"
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_SHA:?Immutable source revision required}"
: "${COSIGN_PRIVATE_KEY:?Configure release signing before tagging}"
export COSIGN_PASSWORD=${COSIGN_PASSWORD:-}

# Reject missing or stale build outputs before signing or contacting the release host.
version=${GITHUB_REF_NAME#v}
payload=("dist/1password_agent_broker-$version-py3-none-any.whl" "dist/1password_agent_broker-$version.tar.gz"
    "dist/1password_agent_broker_sdk-$version-py3-none-any.whl" "dist/1password_agent_broker_sdk-$version.tar.gz"
    "dist/1password-agent-broker-$version.tgz")
shopt -s nullglob
archives=(dist/*.whl dist/*.tar.gz dist/*.tgz)
[ "${#archives[@]}" -eq "${#payload[@]}" ] || {
    echo 'Expected a wheel and source distribution for both packages, plus the chart' >&2
    exit 1
}
for asset in "${payload[@]}"; do
    test -f "$asset"
done

# Declare both distributions inside the signed manifest; older releases omit this marker.
printf '%s\n' '1password-agent-broker' '1password-agent-broker-sdk' >dist/PACKAGES.txt
payload+=(dist/PACKAGES.txt)

# Finalize provenance and payload hashes before signing; the manifest does not hash itself.
mkdir -p dist/verification
printf 'Repository: %s\nTag: %s\nSource commit: %s\n' "$GITHUB_REPOSITORY" "$GITHUB_REF_NAME" "$GITHUB_SHA" >dist/SOURCE.txt
(
    cd dist
    sha256sum ./*.whl ./*.tar.gz ./*.tgz SOURCE.txt PACKAGES.txt >verification/SHA256SUMS
)
cosign public-key --key env://COSIGN_PRIVATE_KEY >dist/verification/cosign.pub
cosign sign-blob --yes --use-signing-config=false --tlog-upload=false --key env://COSIGN_PRIVATE_KEY \
    --bundle dist/verification/SHA256SUMS.sigstore.json dist/verification/SHA256SUMS
cosign verify-blob --insecure-ignore-tlog --key dist/verification/cosign.pub \
    --bundle dist/verification/SHA256SUMS.sigstore.json dist/verification/SHA256SUMS
openssl pkey -pubin -in dist/verification/cosign.pub -outform DER 2>/dev/null |
    openssl dgst -sha256 >dist/verification/fingerprint.txt
printf 'Source commit: %s\n\nVerify SHA256SUMS with the independently trusted signing key, then verify the Python and Helm archives.\n' \
    "$GITHUB_SHA" >dist/verification/release-notes.md
assets=("${payload[@]}" dist/SOURCE.txt dist/verification/SHA256SUMS
    dist/verification/SHA256SUMS.sigstore.json dist/verification/cosign.pub dist/verification/fingerprint.txt)
# Retry incomplete drafts only; never replace bytes in an already published release.
if draft="$(gh release view "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft 2>/dev/null)"; then
    [ "$draft" = true ] || {
        echo 'Release is already published; refusing to replace artifacts' >&2
        exit 1
    }
    gh release upload "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --clobber "${assets[@]}"
else
    gh release create "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --verify-tag --draft \
        --title "$GITHUB_REF_NAME" --notes-file dist/verification/release-notes.md "${assets[@]}"
fi
# The environment-provided signing identity is the trust anchor for this downloaded draft.
checked="$(mktemp -d)"
# Remove only this invocation's disposable verification directory on every exit.
# -> ret::exit_code
cleanup() {
    rm -rf -- "$checked"
}
trap cleanup EXIT
gh release download "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --dir "$checked"
cosign verify-blob --insecure-ignore-tlog --key dist/verification/cosign.pub \
    --bundle "$checked/SHA256SUMS.sigstore.json" "$checked/SHA256SUMS"
downloaded=("$checked"/*)
[ "${#downloaded[@]}" -eq "${#assets[@]}" ] || {
    echo 'Unexpected draft attachment set' >&2
    exit 1
}

# Matching attachment counts alone are insufficient; each downloaded name and byte sequence must match.
for asset in "${assets[@]}"; do
    cmp "$asset" "$checked/$(basename "$asset")"
done
(
    cd "$checked"
    sha256sum --check SHA256SUMS
)

# Only the verified downloaded draft may become visible as a release.
gh release edit "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --draft=false
