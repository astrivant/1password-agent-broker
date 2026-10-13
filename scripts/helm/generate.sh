#!/usr/bin/env bash
# Generate chart documentation and structural schema from annotated values.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
mkdir -p .cache/helm
readme-generator --values helm/1password-agent-broker/values.yaml \
    --readme helm/1password-agent-broker/README.md --schema .cache/helm/values.schema.json
poetry run python scripts/helm/schema.py
