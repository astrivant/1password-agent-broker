#!/usr/bin/env bash
# Recover Python distributions from an authenticated, signed release already on main.
# PYPI_RELEASE_TAG::string GITHUB_REPOSITORY::string GITHUB_OUTPUT::path -> ret::exit_code
set -euo pipefail
: "${PYPI_RELEASE_TAG:?Select the published release tag}"
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_OUTPUT:?GitHub job outputs required}"
[[ $PYPI_RELEASE_TAG =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]

# A dispatch uses the reviewed workflow on main while preserving the original tag's source and bytes.
tag_object=$(gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$PYPI_RELEASE_TAG" --jq 'select(.object.type == "tag") | .object.sha')
[[ $tag_object =~ ^[0-9a-f]{40}$ ]]
source=$(gh api "repos/$GITHUB_REPOSITORY/git/tags/$tag_object" \
    --jq 'select(.verification.verified == true and .object.type == "commit") | .object.sha')
[[ $source =~ ^[0-9a-f]{40}$ ]]
relation=$(gh api "repos/$GITHUB_REPOSITORY/compare/$source...main" --jq .status)
[[ $relation == ahead || $relation == identical ]]
if [[ $GITHUB_EVENT_NAME == push ]]; then
    [[ $source == "$GITHUB_SHA" && $PYPI_RELEASE_TAG == "$GITHUB_REF_NAME" ]]
fi

GITHUB_REF_NAME="$PYPI_RELEASE_TAG" GITHUB_SHA="$source" bash scripts/release/verify.sh pypi-dist
python3 scripts/release/check_pypi.py --version "${PYPI_RELEASE_TAG#v}" --directory pypi-dist --allow-missing
printf 'version=%s\nsource=%s\n' "${PYPI_RELEASE_TAG#v}" "$source" >>"$GITHUB_OUTPUT"
