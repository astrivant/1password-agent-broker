#!/usr/bin/env bash
# Generate chart documentation and structural schema from annotated values.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
chart=helm/1password-agent-broker
mkdir -p .cache/helm
readme-generator --values "$chart/values.yaml" \
    --readme "$chart/README.md" --schema .cache/helm/values.schema.json
poetry run python scripts/helm/schema.py

# Document each supported overlay from its own annotations without duplicating chart defaults.
for values in "$chart"/references/*/values.yaml; do
    readme="${values%/*}/README.md"
    if [[ ! -f "$readme" ]]; then
        printf 'Missing reference README: %s\n' "$readme" >&2
        exit 1
    fi
    readme-generator --values "$values" --readme "$readme"
done
