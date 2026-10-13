#!/usr/bin/env bash
# Create or reuse a repository-scoped release identity and upload secrets through stdin.
# arguments::array<string> -> ret::exit_code
set -euo pipefail
umask 077

# Show the external effects before dependency checks or filesystem mutations.
# ret::exit_code
usage() {
    cat <<'USAGE'
Usage: setup-signing.sh --repo OWNER/REPO [--key-dir DIRECTORY]

Create or reuse a local Cosign key and password, then upload COSIGN_PRIVATE_KEY
and COSIGN_PASSWORD to that repository. No key rotation is performed on retry.
The default directory is $XDG_DATA_HOME/1password-agent-broker/release-keys/OWNER/REPO,
falling back to $HOME/.local/share. Keep this private backup outside Git.
USAGE
}

repository=''
backup_directory=''
while [[ $# -gt 0 ]]; do
    case "$1" in
    --help | -h)
        usage
        exit 0
        ;;
    --repo | --key-dir)
        [[ $# -ge 2 && -n $2 && $2 != --* ]] || {
            usage >&2
            exit 2
        }
        if [[ $1 == --repo ]]; then
            [[ -z $repository ]] || {
                usage >&2
                exit 2
            }
            repository=$2
        else
            [[ -z $backup_directory ]] || {
                usage >&2
                exit 2
            }
            backup_directory=$2
        fi
        shift 2
        ;;
    *)
        usage >&2
        exit 2
        ;;
    esac
done
if [[ ! $repository =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
    usage >&2
    exit 2
fi
backup_directory=${backup_directory:-${XDG_DATA_HOME:-$HOME/.local/share}/1password-agent-broker/release-keys/$repository}
for dependency in openssl cosign gh git; do
    command -v "$dependency" >/dev/null
done

# Serialize this directory's writers, and reject paths that can expose or redirect key material.
[[ ! -L $backup_directory ]] || {
    echo 'Key directory must not be a symlink' >&2
    exit 1
}
mkdir -p "$backup_directory"
backup_directory=$(cd "$backup_directory" && pwd)
if git -C "$backup_directory" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo 'Keep the signing backup outside a Git checkout' >&2
    exit 1
fi
chmod 700 "$backup_directory"
mkdir "$backup_directory/.setup-signing.lock" || {
    echo 'Signing setup already owns this directory' >&2
    exit 1
}
trap 'rm -f "$backup_directory/.setup-signing.lock/public.pem"; rmdir "$backup_directory/.setup-signing.lock"' EXIT
for name in cosign.key cosign.pub cosign.password fingerprint.txt repository; do
    [[ ! -L $backup_directory/$name ]] || {
        echo 'Signing files must not be symlinks' >&2
        exit 1
    }
done
if [[ -f $backup_directory/repository && $(cat "$backup_directory/repository") != "$repository" ]]; then
    echo 'Signing directory belongs to a different repository' >&2
    exit 1
fi

# A partial backup is recovery evidence, not permission to generate a replacement identity.
if [[ ! -f $backup_directory/cosign.key ]]; then
    for name in cosign.pub cosign.password fingerprint.txt repository; do
        [[ ! -e $backup_directory/$name ]] || {
            echo 'Incomplete signing backup; preserve and recover it before retrying' >&2
            exit 1
        }
    done
    export COSIGN_PASSWORD
    COSIGN_PASSWORD=$(openssl rand -base64 32)
    printf '%s' "$COSIGN_PASSWORD" >"$backup_directory/cosign.password"
    cosign generate-key-pair --output-key-prefix "$backup_directory/cosign" >/dev/null
fi
[[ -f $backup_directory/cosign.password ]] || {
    echo 'Missing cosign.password; restore the existing password before retrying (an empty file for an old empty-password key)' >&2
    exit 1
}
chmod 600 "$backup_directory/cosign.key" "$backup_directory/cosign.password"
export COSIGN_PASSWORD
COSIGN_PASSWORD=$(cat "$backup_directory/cosign.password")

# Prove the saved password and public identity agree before updating either repository secret.
cosign public-key --key "$backup_directory/cosign.key" >"$backup_directory/.setup-signing.lock/public.pem"
if [[ -e $backup_directory/cosign.pub ]]; then
    cmp "$backup_directory/cosign.pub" "$backup_directory/.setup-signing.lock/public.pem"
else
    cp "$backup_directory/.setup-signing.lock/public.pem" "$backup_directory/cosign.pub"
fi
fingerprint=$(openssl pkey -pubin -in "$backup_directory/cosign.pub" -outform DER 2>/dev/null | openssl dgst -sha256)
if [[ -f $backup_directory/fingerprint.txt ]]; then
    recorded=$(cat "$backup_directory/fingerprint.txt")
    [[ ${recorded##* } == "${fingerprint##* }" ]] || {
        echo 'Saved signing fingerprint does not match the key' >&2
        exit 1
    }
fi
printf '%s\n' "${fingerprint##* }" >"$backup_directory/fingerprint.txt"
printf '%s\n' "$repository" >"$backup_directory/repository"

# A failed second upload can be retried with this same directory and unchanged key/password.
gh secret set COSIGN_PRIVATE_KEY --repo "$repository" <"$backup_directory/cosign.key"
printf '%s' "$COSIGN_PASSWORD" | gh secret set COSIGN_PASSWORD --repo "$repository"
printf '\nRelease signing secrets configured. Private backup: %s\n' "$backup_directory"
cat "$backup_directory/fingerprint.txt"
