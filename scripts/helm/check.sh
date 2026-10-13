#!/usr/bin/env bash
# Validate generated contracts, render manifests, and package the immutable source chart.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
chart=helm/1password-agent-broker
mkdir -p dist .cache/helm
helm lint "$chart"
helm template broker "$chart" --kube-version 1.30.0 >.cache/helm/rendered.yaml
kubeconform -strict -summary -kubernetes-version 1.30.0 .cache/helm/rendered.yaml
poetry run pytest -n 2 -q pkg/agent_broker/tests/test_helm.py
# The separate lock retains the application project's newer pytest version.
scripts/helm/.venv/bin/python scripts/helm/.venv/bin/hypothesis-helm test "$chart" \
    --whole-chart --config scripts/helm/hypothesis.yaml --max-examples 12 --jobs 1 \
    --time-limit 120s --no-cache --fail error --seed 20261013

# Render the packaged artifact too, proving packaging preserves the reviewed chart output.
version=$(poetry version --short)
helm package "$chart" --version "$version" --app-version "$version" --destination dist
helm lint "dist/1password-agent-broker-$version.tgz"
helm template broker "dist/1password-agent-broker-$version.tgz" >.cache/helm/packaged.yaml
cmp .cache/helm/rendered.yaml .cache/helm/packaged.yaml
