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

# Require the declared PR policy on the host; metadata alone must not pass acceptance.
gh api "repos/$repository/branches/main/protection" |
    jq -e '.required_status_checks.strict
        and (.required_status_checks.checks == [{"context": "PR quality gate", "app_id": 15368}])
        and (.required_pull_request_reviews.required_approving_review_count == 1)
        and .required_pull_request_reviews.dismiss_stale_reviews
        and (.required_pull_request_reviews.require_code_owner_reviews | not)
        and (.enforce_admins.enabled | not)
        and .required_conversation_resolution.enabled
        and (.allow_force_pushes.enabled | not)
        and (.allow_deletions.enabled | not)
        and (.required_linear_history.enabled | not)
        and (.restrictions == null)'
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
