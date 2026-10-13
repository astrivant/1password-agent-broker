#!/usr/bin/env bash
# Validate repository hosting and optionally inspect the published release contract.
# repository::owner/name tag::optional_string -> ret::exit_code
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 || $1 != */* ]]; then
    echo 'Usage: github.sh OWNER/REPO [vX.Y.Z]' >&2
    exit 2
fi
repository=$1

# Inspect host state directly; a settings file alone does not establish configuration.
gh api "repos/$repository" --jq '{default_branch,description,homepage,has_issues,has_wiki,delete_branch_on_merge}' |
    jq -e '.default_branch == "main" and .has_issues and (.has_wiki | not) and .delete_branch_on_merge
        and (.description | length > 0) and (.homepage | endswith("#quick-start"))'
gh api "repos/$repository/actions/permissions" --jq .enabled | jq -e '. == true'
gh api "repos/$repository/actions/permissions/workflow" |
    jq -e '.default_workflow_permissions == "read" and (.can_approve_pull_request_reviews | not)'
gh api "repos/$repository/commits/main" --jq .commit.verification.verified | jq -e '. == true'
gh secret list --repo "$repository" --json name | jq -e 'any(.[]; .name == "COSIGN_PRIVATE_KEY")'
gh api "repos/$repository/actions/workflows/ci.yml" --jq '.state == "active"' | jq -e '. == true'

# Policy decisions remain explicit: display evidence without imposing a new protection rule.
gh api "repos/$repository/branches/main" --jq '{branch: .name, protected}'
gh api "repos/$repository/rulesets" --jq '[.[] | {name,enforcement}]'

if [[ $# == 2 ]]; then
    release_tag=$2
    gh release view "$release_tag" --repo "$repository" --json isDraft,isPrerelease,assets,url |
        jq -e '(.isDraft | not) and (.isPrerelease | not)
            and ([.assets[].name] as $names | all(["SOURCE.txt", "SHA256SUMS", "SHA256SUMS.sigstore.json", "cosign.pub", "fingerprint.txt"][]; . as $name | $names | index($name)))
            and any(.assets[]; .name | endswith(".whl"))
            and any(.assets[]; .name | endswith(".tar.gz"))
            and any(.assets[]; .name | endswith(".tgz"))'
fi
