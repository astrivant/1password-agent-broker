#!/usr/bin/env bash
# Create a cosign release identity and project its private key through gh stdin.
# repository::string backup_directory::path -> ret::exit_code
set -euo pipefail
umask 077
if [[ $# != 2 || $1 != */* ]]; then
    echo 'Usage: setup-signing.sh OWNER/REPO NEW_PRIVATE_BACKUP_DIRECTORY' >&2
    exit 2
fi
repository=$1
backup_directory=$2
for dependency in openssl cosign gh; do
    command -v "$dependency" >/dev/null
done
# Refuse an existing directory so a previous signing identity cannot be overwritten.
mkdir -m 700 "$backup_directory"
backup_directory=$(cd "$backup_directory" && pwd)
trap 'rm -f "$backup_directory/import.pem"' EXIT
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$backup_directory/import.pem" 2>/dev/null
export COSIGN_PASSWORD=''
cosign import-key-pair --key "$backup_directory/import.pem" --output-key-prefix "$backup_directory/cosign" >/dev/null
cosign public-key --key "$backup_directory/cosign.key" >"$backup_directory/cosign.pub"
openssl pkey -pubin -in "$backup_directory/cosign.pub" -outform DER 2>/dev/null |
    openssl dgst -sha256 >"$backup_directory/fingerprint.txt"

# Send only through stdin; neither shell arguments nor ordinary logs may contain the private key.
gh secret set COSIGN_PRIVATE_KEY --repo "$repository" <"$backup_directory/cosign.key"
printf '\nRelease signing secret configured. Private backup: %s\n' "$backup_directory"
cat "$backup_directory/fingerprint.txt"
