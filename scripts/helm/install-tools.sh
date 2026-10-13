#!/usr/bin/env bash
# Install checksum-verified chart tools for the Linux AMD64 CI runner.
# GITHUB_PATH::path RUNNER_TEMP::path -> ret::exit_code
set -euo pipefail
: "${RUNNER_TEMP:?CI temporary directory required}"
: "${GITHUB_PATH:?CI path export required}"
directory="$RUNNER_TEMP/broker-helm-tools"
mkdir -p "$directory"
cd "$directory"
curl --fail --silent --show-error --location --retry 3 --connect-timeout 10 --max-time 60 \
    -O https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz \
    -O https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz.sha256sum

# Check downloaded archive bytes before extracting executables into the runner path.
sha256sum --check helm-v4.3.0-linux-amd64.tar.gz.sha256sum
tar -xzf helm-v4.3.0-linux-amd64.tar.gz linux-amd64/helm
mv linux-amd64/helm ./helm
gh release download v0.8.0 --repo yannh/kubeconform --dir "$directory" \
    --pattern kubeconform-linux-amd64.tar.gz --pattern CHECKSUMS
sha256sum --check --ignore-missing CHECKSUMS
tar -xzf kubeconform-linux-amd64.tar.gz kubeconform
echo "$directory" >>"$GITHUB_PATH"
