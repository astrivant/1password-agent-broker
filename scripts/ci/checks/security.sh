#!/usr/bin/env bash
# Scan with pinned Trivy; raw matches never leave temporary memory-backed storage.
# output_directory::path -> ret::exit_code
set -euo pipefail
output_directory=${1:?Output directory required}
mkdir -p "$output_directory" .cache/trivy
output_directory=$(cd "$output_directory" && pwd)
raw_directory=$(mktemp -d /dev/shm/agent-broker-trivy.XXXXXX)
trap 'rm -rf "$raw_directory"' EXIT
chmod 700 "$raw_directory"
docker run --rm --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$PWD,target=/workspace,readonly" \
    --mount "type=bind,source=$PWD/.cache/trivy,target=/cache" \
    --mount "type=bind,source=$raw_directory,target=/raw" \
    aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa \
    fs --cache-dir /cache --scanners vuln,secret \
    --skip-dirs .git --skip-dirs .venv --skip-dirs .cache --skip-dirs dist \
    --format json --output /raw/report.json /workspace

# Publish only the redacted allowlist; raw scanner matches are deleted with the private temporary directory.
python scripts/ci/checks/trivy_report.py "$raw_directory/report.json" "$output_directory/security.json"
