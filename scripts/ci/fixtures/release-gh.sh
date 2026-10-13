#!/usr/bin/env bash
# Model release/secret operations locally without persisting stdin or making network calls.
# arguments::array<string> GH_STUB_ASSETS::path GH_STUB_KEYS::path -> ret::exit_code
set -euo pipefail
if [[ $1 == secret && $2 == set ]]; then
    [[ $# == 5 && $4 == --repo && $5 == synthetic/repository ]]
    case "$3" in
    COSIGN_PRIVATE_KEY) cmp - "$GH_STUB_KEYS/cosign.key" ;;
    COSIGN_PASSWORD) cmp - "$GH_STUB_KEYS/cosign.password" ;;
    *) exit 2 ;;
    esac
    printf '%s\n' "$3" >>"$GH_STUB_CALLS"
    [[ $3 != COSIGN_PASSWORD || ${GH_STUB_FAIL_PASSWORD:-0} == 0 ]]
elif [[ $1 == release && $2 == view ]]; then
    if [[ -e "$GH_STUB_ASSETS/published" ]]; then echo false; else exit 1; fi
elif [[ $1 == release && $2 == create ]]; then
    [[ " $* " == *" --draft "* ]]
    for argument in "$@"; do
        if [[ $argument == dist/* && $argument != */release-notes.md ]]; then
            cp "$argument" "$GH_STUB_ASSETS/"
        fi
    done
elif [[ $1 == release && $2 == download ]]; then
    while [[ $1 != --dir ]]; do shift; done
    for asset in "$GH_STUB_ASSETS/"*; do
        if [[ $(basename "$asset") != published ]]; then cp "$asset" "$2/"; fi
    done
    if [[ ${GH_STUB_CORRUPT:-0} == 1 ]]; then
        printf 'corrupted\n' >>"$2/SOURCE.txt"
    fi
elif [[ $1 == release && $2 == edit ]]; then
    [[ " $* " == *" --draft=false "* ]]
    touch "$GH_STUB_ASSETS/published"
else
    exit 2
fi
