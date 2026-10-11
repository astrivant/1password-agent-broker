#!/usr/bin/env bash
# Sign the exact checked distributions and publish their verification artifacts.
# environment::GitHub_Actions -> ret::exit_code
set -euo pipefail
umask 077
: "${GITHUB_REF_NAME:?Version tag required}"
: "${GITHUB_REPOSITORY:?Repository required}"
: "${COSIGN_PRIVATE_KEY:?Configure release signing before tagging}"
export COSIGN_PASSWORD=${COSIGN_PASSWORD:-}
mkdir -p dist/verification
(
    cd dist
    sha256sum ./*.whl ./*.tar.gz >verification/SHA256SUMS
)
cosign public-key --key env://COSIGN_PRIVATE_KEY >dist/verification/cosign.pub
cosign sign-blob --yes --tlog-upload=false --key env://COSIGN_PRIVATE_KEY \
    --output-signature dist/verification/SHA256SUMS.sig dist/verification/SHA256SUMS
cosign verify-blob --insecure-ignore-tlog --key dist/verification/cosign.pub \
    --signature dist/verification/SHA256SUMS.sig dist/verification/SHA256SUMS
openssl pkey -pubin -in dist/verification/cosign.pub -outform DER 2>/dev/null |
    openssl dgst -sha256 >dist/verification/fingerprint.txt
printf 'Source commit: %s\n\nVerify SHA256SUMS with the independently trusted signing key, then verify the distributions.\n' \
    "$GITHUB_SHA" >dist/verification/release-notes.md
gh release create "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --verify-tag \
    --title "$GITHUB_REF_NAME" --notes-file dist/verification/release-notes.md \
    dist/*.whl dist/*.tar.gz dist/verification/SHA256SUMS dist/verification/SHA256SUMS.sig \
    dist/verification/cosign.pub dist/verification/fingerprint.txt
