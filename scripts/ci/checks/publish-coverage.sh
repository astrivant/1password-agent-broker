#!/usr/bin/env bash
# Publish measured coverage with a GitHub-signed Contents API commit.
# environment::GitHub_Actions -> ret::exit_code
set -euo pipefail
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_SHA:?Measured source commit required}"

# Ignore late results from a main revision that has already been replaced.
current=$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main" --jq .object.sha)
if [[ "$current" != "$GITHUB_SHA" ]]; then
    echo 'Main has advanced; keeping its coverage publication unchanged.'
    exit 0
fi

# A derived branch keeps generated badge writes out of main and avoids CI loops.
if ! gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/coverage" --silent 2>/dev/null; then
    gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs" \
        -f ref=refs/heads/coverage -f sha="$GITHUB_SHA" --silent
fi
endpoint="repos/$GITHUB_REPOSITORY/contents/badges/coverage.json"
encoded=$(base64 <artifacts/coverage/coverage.json | tr -d '\n')
previous=$(gh api "$endpoint?ref=coverage" 2>/dev/null || true)

# Stable content produces no new commit; updates include the expected blob revision.
if [[ -n "$previous" ]] && [[ $(jq -r .content <<<"$previous" | tr -d '\n') == "$encoded" ]]; then
    echo 'Coverage is unchanged.'
    exit 0
fi
arguments=(--method PUT "$endpoint" -f branch=coverage -f "content=$encoded"
    -f "message=Update measured Python coverage for $GITHUB_SHA")
if [[ -n "$previous" ]]; then
    arguments+=(-f "sha=$(jq -r .sha <<<"$previous")")
fi
gh api "${arguments[@]}" --jq '.commit.html_url'
