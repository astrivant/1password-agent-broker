# Development

## Environment and checks

Use Python 3.12 or newer (excluding 3.14.1), Poetry 2.5.1, Git, and actionlint 1.7.12. Dependencies are pinned in `pyproject.toml` and `poetry.lock`; ordinary CI never re-resolves them.

```sh
poetry config virtualenvs.in-project true --local
poetry install
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest -n 4 --cov=agent_broker --cov-report=term-missing
poetry run agent-broker demo
```

Keep the project's virtual environment first on `PATH` when invoking hooks or subprocess tests. The MCP subprocess test uses the current Python executable. Ruff, strict mypy, pydocstyle, pydoclint, SQLFluff, ShellCheck, shfmt, and actionlint cover the maintained languages. `scripts/documentation/contents.py` regenerates README navigation to a maximum of three heading levels.

Python uses typed Google-style multiline docstrings, with `Returns: None` for ordinary void functions. Constructors document inputs and side effects without a return section, as required by pydoclint. The generic conversion helper retains `TypeVar` syntax because current pydocstyle cannot parse PEP 695 function type parameters; this does not alter its typed contract.

SQLite transaction behavior is configured through the driver's `IMMEDIATE` isolation level. Reservation is an atomic `INSERT OR IGNORE` followed by a read in that write transaction. SQL remains in packaged `.sql` files and is linted independently.

## Layout

| Path | Responsibility |
| --- | --- |
| `pkg/agent_broker/` | Typed contracts, authority, durable ledger, credential provider, TLS and MCP adapters. |
| `pkg/agent_broker/resources/` | Closed JSON schemas and parameterized SQLite statements. |
| `pkg/agent_broker/testing/` | Generated certificates and synthetic local service shared by demo/tests. |
| `pkg/agent_broker/tests/` | Package-local security and integration regressions. |
| `scripts/` | Documentation, CI redaction, and release operations. |
| `.github/` | One shallow CI workflow, cached environment action, and repository metadata. |

## Containers

The production image uses a non-root UID/GID 10001, Tini as PID 1, no development dependencies, the official 1Password SDK, and an installed wheel. Debian provides the SDK's glibc and libssl3 native requirements. The build loads the SDK's native library and validates a synthetic reference offline. Tini forwards signals to the process group; the Python server stops accepting work and joins its owned threads. Use a private network, read-only root, dropped capabilities, and limits for a deployment.

```sh
docker compose --profile demo run --build --rm demo
docker compose --profile development run --build --rm development
```

These profiles run synthetic work only and require no credentials. The development target contains the locked development tools. For a real broker, override the command with `agent-broker serve ... --host 0.0.0.0`, mount operator configuration and certificate files read-only, and give only UID 10001 a private writable ledger volume. Inject the service-account token through your runtime secret facility into the broker process alone. Never bake it into a Dockerfile or Compose file.

The SDK is pinned to 0.4.1 in `pyproject.toml` and `poetry.lock`. Its published wheels stop at CPython 3.13; Python 3.14 installs its source distribution with bundled native libraries. The package omits `py.typed`, so mypy follows its inline annotations through a scoped `follow_untyped_imports` override. Tests exercise the actual authentication and resolution adapters against a synthetic native boundary, plus real offline native reference validation. They never authenticate to a live account.

## CI and pinned tools

Lint, Python-version tests, package/container verification, and security scanning start independently. Only release publication waits for all of them. A coverage leaf job reads the Python 3.14 report after both test versions pass and publishes a Shields endpoint payload to the `coverage` branch through GitHub's signed Contents API. Unchanged percentages create no commit; obsolete main runs skip publication. The README badge shows measured line coverage, not general CI status. Python virtual environments are cached by OS, architecture, exact Python version, and lock/metadata hashes. Trivy's vulnerability database uses a six-hour cache window; scan results are never cached as if they were current.

Pins outside Poetry's lockfile:

| Component | Version | Source of truth |
| --- | --- | --- |
| Python container | 3.14.8 slim Trixie, digest pinned | `Dockerfile`, [Docker Official Image](https://hub.docker.com/_/python). |
| Tini | Debian `0.19.0-3+b8` | `Dockerfile`, [upstream](https://github.com/krallin/tini). |
| Poetry | 2.5.1 | Dockerfile and `.github/actions/python/action.yml`. |
| Hosted Python | 3.12.15 and 3.14.8 | CI compatibility checks. |
| actionlint | 1.7.12 | CI download verified against its release checksums. |
| Trivy | 0.75.0, digest pinned | `scripts/ci/checks/security.sh`. |
| Cosign | 3.1.3 | CI release job. |
| checkout / setup-python | 7.0.1 / 7.0.0 | Immutable SHA pins beside version comments. |
| cache | 6.1.0 | Composite environment action and security job. |
| upload-artifact / download-artifact | 7.0.2 / 8.0.2 | CI artifact boundaries. |
| cosign-installer | 4.1.2 | CI release tooling. |

System CA certificates and Debian security updates are installed from the pinned image's supported distribution repositories at build time. Their package revisions are intentionally not frozen against security updates; the resulting container should be identified by its digest. Dependabot proposes dependency/action/image updates; review and rerun the supported contracts before merging.

## Release signing

Before your first tag, install OpenSSL, Cosign, and authenticated `gh`, then run:

```sh
bash scripts/release/setup-signing.sh OWNER/REPO /private/new-release-key-backup
```

The script generates a P-256 PEM key, imports it into Cosign, writes a private backup, removes the temporary PEM, and sends the signing key to the repository's `COSIGN_PRIVATE_KEY` secret through stdin. It prints only the backup location and public-key fingerprint. It refuses to overwrite an existing backup directory. The default key has an empty Cosign passphrase; protect the backup using encrypted storage and mode 0700. For an existing password-protected key, additionally configure `COSIGN_PASSWORD` in GitHub.

For a new project, exercise the first signed release with `v0.0.1` after hooks and main CI pass. For an existing release sequence, use its next compatible version; never move an existing tag. Update package metadata, commit, and push a matching signed `vX.Y.Z` tag. CI signs checksums for the tested wheel and source distribution, verifies that signature, then uses `gh release create` to attach distributions, `SHA256SUMS`, its Sigstore signature bundle, the public key, and fingerprint. Publication is enabled only in the upstream repository by default; forks must deliberately adjust that guard. No PyPI upload is configured.

Download all release files into one directory. Verify the public-key fingerprint against an independently trusted maintainer record, then:

```sh
cosign verify-blob --insecure-ignore-tlog --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS
sha256sum --check SHA256SUMS
```

On macOS use `shasum -a 256 --check SHA256SUMS` for the second command. A synthetic signing check exercises these scripts in CI with temporary keys and a local GitHub stub. Cosign 3 requires a Sigstore bundle; the check prevents older signature-only flags from silently reaching a tag pipeline. This key-based release scheme does not publish to a transparency log. The public key attached to a release is convenient verification material, not its own trust anchor.

Release acceptance includes the real tag pipeline: download its assets, authenticate the checksum bundle with the independently retained signing key, check every distribution hash, and run the installed wheel's demo. A queued workflow or a green main run alone does not verify release publication.

The initial upstream signing key fingerprint (SHA-256 of DER SubjectPublicKeyInfo) is `c025b0ffd4e676db5710697b756ed9b4a46025966b26faface444f3318c8513f`. Compare against a separately trusted copy of this record; downloading a replacement key and fingerprint from the same untrusted release is insufficient.
