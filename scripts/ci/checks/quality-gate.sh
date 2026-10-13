#!/usr/bin/env bash
# Reject missing, skipped, failed or cancelled prerequisite jobs at the merge boundary.
# NEEDS_JSON::json_object -> ret::exit_code
set -euo pipefail

# Require the complete producer set; an empty or partial needs object is not success.
jq -e '
    type == "object"
    and keys == ["charts", "lint", "package", "release-contract", "security", "tests"]
    and all(.[]; .result == "success")
' <<<"${NEEDS_JSON:?Set NEEDS_JSON to the GitHub Actions needs object}"
