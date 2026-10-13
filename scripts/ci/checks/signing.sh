#!/usr/bin/env bash
# Exercise key preservation and partial-upload recovery with real Cosign and a local gh stub.
# repository_root::cwd -> ret::exit_code
set -euo pipefail
umask 077
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin"
cp scripts/ci/fixtures/release-gh.sh "$scratch/bin/gh"
chmod +x "$scratch/bin/gh"
export PATH="$scratch/bin:$PATH" GH_STUB_KEYS="$scratch/keys" GH_STUB_CALLS="$scratch/calls"
setup="$PWD/scripts/release/setup-signing.sh"
arguments=(--repo synthetic/repository --key-dir "$GH_STUB_KEYS")

# Help is side-effect free; an explicit destination is mandatory before creating key material.
bash "$setup" --help >/dev/null
if bash "$setup" --key-dir "$GH_STUB_KEYS" >"$scratch/output" 2>&1; then exit 1; fi
test ! -e "$GH_STUB_KEYS"
test ! -e "$GH_STUB_CALLS"

# The first upload succeeds and the second fails; retry must use exactly the same key and password.
if GH_STUB_FAIL_PASSWORD=1 bash "$setup" "${arguments[@]}" >"$scratch/output" 2>&1; then exit 1; fi
test -s "$GH_STUB_KEYS/cosign.key"
test -s "$GH_STUB_KEYS/cosign.password"
test ! -e "$GH_STUB_KEYS/.setup-signing.lock"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 2
cp "$GH_STUB_KEYS/cosign.key" "$scratch/original.key"
cp "$GH_STUB_KEYS/cosign.password" "$scratch/original.password"
bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1
bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1
cmp "$scratch/original.key" "$GH_STUB_KEYS/cosign.key"
cmp "$scratch/original.password" "$GH_STUB_KEYS/cosign.password"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 6
test -z "$(find "$GH_STUB_KEYS" -type d ! -perm 700 -print)"
test -z "$(find "$GH_STUB_KEYS/cosign.key" "$GH_STUB_KEYS/cosign.password" ! -perm 600 -print)"
if grep -F -q -f "$GH_STUB_KEYS/cosign.password" "$scratch/output"; then exit 1; fi
if grep -q 'BEGIN ENCRYPTED SIGSTORE PRIVATE KEY' "$scratch/output"; then exit 1; fi

# Wrong scope, missing password and inconsistent public identity fail before any secret upload.
if bash "$setup" --repo another/repository --key-dir "$GH_STUB_KEYS" >>"$scratch/output" 2>&1; then exit 1; fi
mv "$GH_STUB_KEYS/cosign.password" "$scratch/saved.password"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
mv "$scratch/saved.password" "$GH_STUB_KEYS/cosign.password"
cp "$GH_STUB_KEYS/cosign.pub" "$scratch/saved.pub"
printf 'mismatched public key\n' >"$GH_STUB_KEYS/cosign.pub"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
cp "$scratch/saved.pub" "$GH_STUB_KEYS/cosign.pub"
cp "$GH_STUB_KEYS/fingerprint.txt" "$scratch/saved.fingerprint"
printf 'wrong-fingerprint\n' >"$GH_STUB_KEYS/fingerprint.txt"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
cp "$scratch/saved.fingerprint" "$GH_STUB_KEYS/fingerprint.txt"
printf 'wrong-password' >"$GH_STUB_KEYS/cosign.password"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
cp "$scratch/original.password" "$GH_STUB_KEYS/cosign.password"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 6
cmp "$scratch/original.key" "$GH_STUB_KEYS/cosign.key"

# Never turn incomplete backups, concurrent writers or linked paths into implicit rotation.
mkdir "$scratch/partial" "$GH_STUB_KEYS/.setup-signing.lock"
printf 'retained-password' >"$scratch/partial/cosign.password"
if bash "$setup" --repo synthetic/repository --key-dir "$scratch/partial" >>"$scratch/output" 2>&1; then exit 1; fi
test ! -e "$scratch/partial/cosign.key"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
rmdir "$GH_STUB_KEYS/.setup-signing.lock"
ln -s "$GH_STUB_KEYS" "$scratch/linked-keys"
if bash "$setup" --repo synthetic/repository --key-dir "$scratch/linked-keys" >>"$scratch/output" 2>&1; then exit 1; fi
mv "$GH_STUB_KEYS/cosign.password" "$scratch/linked.password"
ln -s "$scratch/linked.password" "$GH_STUB_KEYS/cosign.password"
if bash "$setup" "${arguments[@]}" >>"$scratch/output" 2>&1; then exit 1; fi
rm "$GH_STUB_KEYS/cosign.password"
mv "$scratch/linked.password" "$GH_STUB_KEYS/cosign.password"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 6

# Existing empty-password keys remain usable when their explicit empty password file is present.
mkdir "$scratch/legacy"
COSIGN_PASSWORD='' cosign generate-key-pair --output-key-prefix "$scratch/legacy/cosign" >"$scratch/legacy-output" 2>&1
touch "$scratch/legacy/cosign.password"
cp "$scratch/legacy/cosign.key" "$scratch/legacy-original.key"
GH_STUB_KEYS="$scratch/legacy" bash "$setup" --repo synthetic/repository --key-dir "$scratch/legacy" >>"$scratch/output" 2>&1
cmp "$scratch/legacy-original.key" "$scratch/legacy/cosign.key"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 8

# Default locations remain repository-scoped, and an explicit checkout path cannot receive keys.
default_keys="$scratch/data/1password-agent-broker/release-keys/synthetic/repository"
XDG_DATA_HOME="$scratch/data" GH_STUB_KEYS="$default_keys" bash "$setup" --repo synthetic/repository >>"$scratch/output" 2>&1
test -s "$default_keys/cosign.key"
git init -q "$scratch/checkout"
if bash "$setup" --repo synthetic/repository --key-dir "$scratch/checkout/keys" >>"$scratch/output" 2>&1; then exit 1; fi
test ! -e "$scratch/checkout/keys/cosign.key"
test "$(wc -l <"$GH_STUB_CALLS")" -eq 10
printf 'Signing setup: creation, repeated reuse, partial upload, scope and recovery checks passed.\n'
