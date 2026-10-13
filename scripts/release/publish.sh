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
mkdir -p dist/verification
printf 'Repository: %s\nTag: %s\nSource commit: %s\n' "$GITHUB_REPOSITORY" "$GITHUB_REF_NAME" "$GITHUB_SHA" >dist/SOURCE.txt
(
    cd dist
    sha256sum ./*.whl ./*.tar.gz ./*.tgz SOURCE.txt >verification/SHA256SUMS
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
assets=(dist/*.whl dist/*.tar.gz dist/*.tgz dist/SOURCE.txt dist/verification/SHA256SUMS
    dist/verification/SHA256SUMS.sigstore.json dist/verification/cosign.pub dist/verification/fingerprint.txt)
# Retry incomplete drafts only; never replace bytes in an already published release.
if draft=$(gh release view "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft 2>/dev/null); then
    [[ $draft == true ]] || {
        echo 'Release is already published; refusing to replace artifacts' >&2
        exit 1
    }
    gh release upload "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --clobber "${assets[@]}"
else
    gh release create "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --verify-tag --draft \
        --title "$GITHUB_REF_NAME" --notes-file dist/verification/release-notes.md "${assets[@]}"
fi
# The environment-provided signing identity is the trust anchor for this downloaded draft.
checked=$(mktemp -d)
trap 'rm -rf "$checked"' EXIT
gh release download "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --dir "$checked"
cosign verify-blob --insecure-ignore-tlog --key dist/verification/cosign.pub \
    --bundle "$checked/SHA256SUMS.sigstore.json" "$checked/SHA256SUMS"
downloaded=("$checked"/*)
[[ ${#downloaded[@]} -eq ${#assets[@]} ]] || {
    echo 'Unexpected draft attachment set' >&2
    exit 1
}
for asset in "${assets[@]}"; do
    cmp "$asset" "$checked/$(basename "$asset")"
done
(
    cd "$checked"
    sha256sum --check SHA256SUMS
)
gh release edit "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --draft=false
