# Development

## Environment and checks

Use Python 3.12 or newer (excluding 3.14.1), Poetry 2.5.1, Node.js 26.10.0, Git, and actionlint 1.7.12. Python dependencies and documentation tools have committed lockfiles; ordinary CI never re-resolves them.

```sh
poetry config virtualenvs.in-project true --local
poetry install
npm ci --prefix scripts/documentation --ignore-scripts --no-fund
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest -n 4 --cov=agent_broker --cov-report=term-missing
poetry run agent-broker demo
```

Select the project's `VIRTUAL_ENV` as well as putting its `bin` directory first on `PATH` when invoking hooks or subprocess tests. An inherited environment selector can override the executable you intended to use. The MCP subprocess test uses the current Python executable. Ruff, strict mypy, pydocstyle, pydoclint, SQLFluff, ShellCheck, shfmt, and actionlint cover the maintained languages. `scripts/documentation/contents.py` regenerates root and nested README navigation to a maximum of three heading levels.

The `documentation-syntax` hook checks all Git-owned Markdown and standalone `.mmd`/`.mermaid` files with remark, KaTeX, and Mermaid's parser. It reports source locations without rewriting files or launching a browser. ESLint checks the JavaScript tool itself; `npm --prefix scripts/documentation test` runs its positive and negative regressions. CI runs the same hook and tests from the npm lockfile.

Use `$...$` or dollar/backtick pairs for inline math, and `$$` blocks or `math` fences for display math. Escape literal dollars as `\$` or use `<span>$</span>`. Keep illustrative source inside ordinary code spans/fences. Backslash-only math delimiters are rejected because hosted Markdown does not reliably recognize them. Use fenced `mermaid` diagrams. See the [GitHub math contract](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions), [GitLab math contract](https://docs.gitlab.com/user/markdown/#math-equations), and [Mermaid parser API](https://mermaid.js.org/config/usage.html#syntax-validation-without-rendering).

Math validation deliberately uses KaTeX's strict portable subset. GitHub uses MathJax and GitLab uses KaTeX; this check does not claim identical engine support or validate mathematical truth. The lockfile overrides nested KaTeX copies to the patched direct version to address GHSA-238p-pmpm-9mq7. Mermaid syntax validation does not verify diagram layout or the host's installed Mermaid version. Preview changed equations and diagrams on the intended host before merging, and use an exported visual for unsupported presentation features.

Python uses typed Google-style multiline docstrings, with `Returns: None` for ordinary void functions. Constructors document inputs and side effects without a return section, as required by pydoclint. The generic conversion helper retains `TypeVar` syntax because current pydocstyle cannot parse PEP 695 function type parameters; this does not alter its typed contract.

Add intent comments before significant blocks, loops, and branches, with a blank line separating logical blocks where the language permits. Explain the decision or invariant a maintainer must preserve: trust boundaries, transaction ordering, replay and cancellation semantics, resource ownership, bounded waits, and publication gates. Keep docstrings focused on the callable's contract and comments on the local implementation reason. Avoid narrating obvious syntax or repeating the docstring.

Review comments alongside implementation and tests so they describe observed behavior, including uncertainty and failure paths. Apply the same practice to Python, SQL, shell, tests, and Helm templates. For comment-only changes, verify that executable structure and rendered manifests remain equivalent, then run the relevant repository checks. Edit maintained sources instead of generated output; preserve whitespace-sensitive template behavior.

SQLite transaction behavior is configured through the driver's `IMMEDIATE` isolation level. Reservation is an atomic `INSERT ... ON CONFLICT DO NOTHING` followed by a read in that write transaction. SQL remains in packaged `.sql` files and is linted independently.

### CODEOWNERS validation

The `codeowners` hook runs [codeowners-validator v0.7.4](https://github.com/mszostok/codeowners-validator/tree/7f3f5e28c6d7b8dfae5731e54ce2272ca384592f) against the complete ownership file on every invocation, including changes that delete or rename owned paths. It rejects malformed owner syntax, duplicate patterns, and patterns matching no files. The hook pins its source commit and Go 1.27.2 in `.pre-commit-config.yaml`; pre-commit downloads and builds the isolated tool environment on first use, then reuses its cache. No system Go installation is required.

Run `poetry run pre-commit run codeowners --all-files` for the focused check. CI runs it through the same all-files pre-commit command. These checks need no GitHub token after installation. Owner existence, team membership and repository permissions require a separate hosted review; this offline hook does not establish review eligibility or require every file to have an owner. Preserve intended last-match precedence when changing rules.

## Layout

| Path | Responsibility |
| --- | --- |
| `pkg/agent_broker/` | Typed contracts, authority, durable ledger, credential provider, TLS and MCP adapters. |
| `pkg/agent_broker/resources/` | Closed JSON schemas and parameterized SQLite/PostgreSQL statements. |
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

### Pull request merge policy

The [repository settings](../.github/settings.yml) declare protection for `main`: one independent approval, stale-approval dismissal, resolved review conversations, and an up-to-date branch with a successful `PR quality gate` from GitHub Actions. The gate joins lint, both Python test versions, package/container checks, chart checks, the synthetic release contract, and security scanning. Its `always()` condition exposes failed or skipped prerequisites; every required result must be `success`. Tag-only publication and main-only coverage jobs are excluded. The required check name remains stable when the Python matrix changes.

Administrators retain GitHub's protection bypass. An agent may use it only with explicit maintainer approval for the particular merge and after all required CI checks pass; record that approval and the tested revision in the PR. This is an operating rule: GitHub's administrator bypass can also bypass status checks. With a single eligible reviewer, author-created PRs need another eligible reviewer or an explicitly approved administrator override. CODEOWNERS routes review but does not itself supply independent approval.

The [Settings app](https://github.com/repository-settings/app/blob/master/docs/configuration.md) applies this file only when configured for the repository and the change reaches the default branch. Otherwise an authorized repository administrator must apply the equivalent [branch-protection API policy](https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection). Register and verify the new gate on a PR before requiring it, then run `bash scripts/qa/github.sh astrivant/1password-agent-broker` to check actual host state. Update older PR branches after the workflow merges so they produce the required gate. The QA command is read-only and fails when protection is absent or differs from this baseline.

### Validation graph and tool versions

Lint, Python-version tests, package/container verification, chart checks, and security scanning start independently. The merge gate and release publication join their required results. A coverage leaf job reads the Python 3.14 report after both test versions pass and publishes a Shields endpoint payload to the `coverage` branch through GitHub's signed Contents API. Unchanged percentages create no commit; obsolete main runs skip publication. The README badge shows measured line coverage, not general CI status. Python virtual environments are cached by OS, architecture, exact Python version, and lock/metadata hashes. Trivy's vulnerability database uses a six-hour cache window; scan results are never cached as if they were current.

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
bash scripts/release/setup-signing.sh --repo OWNER/REPO --key-dir /private/release-key-backup
```

The helper uses [Cosign's key management](https://docs.sigstore.dev/cosign/key_management/signing_with_self-managed_keys/) to create a password-protected key or validate and reuse an existing one. It sends `COSIGN_PRIVATE_KEY` and `COSIGN_PASSWORD` through [GitHub CLI stdin](https://cli.github.com/manual/gh_secret_set) to the explicitly selected repository. `--help` has no side effects. Omitting `--key-dir` selects `$XDG_DATA_HOME/1password-agent-broker/release-keys/OWNER/REPO`, with `$HOME/.local/share` as the base fallback.

The private directory holds `cosign.key`, `cosign.password`, `cosign.pub`, `fingerprint.txt` and a repository binding. The key and password use mode 0600 and the directory uses 0700; keep them together on encrypted storage outside Git. Keeping the password beside the encrypted key supports recovery but does not protect against someone who can read that directory. Ordinary output contains only status, the backup path and the public-key fingerprint. No real secrets are used by the synthetic checks.

If either upload fails, rerun the same command with the same directory. Existing private-key bytes and password are retained; a different repository binding, invalid password, mismatched public key/fingerprint, linked key path or incomplete backup blocks upload. A directory lock excludes concurrent setup; after an unclean termination, confirm the prior process has stopped before removing its `.setup-signing.lock`. Restore incomplete backups from trusted copies rather than deleting them to trigger key generation. Key rotation is a separate maintainer decision, including updating independently trusted fingerprints.

Earlier helper versions used positional `OWNER/REPO DIRECTORY` arguments and an empty password. Use the explicit flags above for the same directory. If that older backup has no `cosign.password`, create an empty private file there only when the key's original password was empty; otherwise restore its actual password. This preserves the original signing identity. The helper does not rotate or recover lost keys.

For a new project, exercise the first signed release with `v0.0.1` after hooks and main CI pass. For an existing release sequence, use its next compatible version; never move an existing tag. Update package metadata, commit, and push a matching signed `vX.Y.Z` tag. CI packages the Helm archive alongside the tested wheel and source distribution, signs checksums including `SOURCE.txt`, and assembles a draft GitHub release. It downloads and verifies the complete attachment set before publishing. Interrupted drafts can be retried; published releases are never overwritten. Attachments include the archives, source/tag provenance, `SHA256SUMS`, its Sigstore signature bundle, the public key, and fingerprint. Publication is enabled only in the upstream repository by default; forks must deliberately adjust that guard. PyPI publication follows verification of the GitHub release.

Download all release files into one directory. Verify the public-key fingerprint against an independently trusted maintainer record, then:

```sh
cosign verify-blob --insecure-ignore-tlog --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS
sha256sum --check SHA256SUMS
```

On macOS use `shasum -a 256 --check SHA256SUMS` for the second command. A synthetic signing check exercises these scripts in CI with temporary keys and a local GitHub stub. Cosign 3 requires a Sigstore bundle; the check prevents older signature-only flags from silently reaching a tag pipeline. This key-based release scheme does not publish to a transparency log. The public key attached to a release is convenient verification material, not its own trust anchor.

A terminal tag job runs even if publication was skipped and verifies the complete downloaded release against the independently pinned signing-key fingerprint and expected source revision. Release acceptance includes the real tag pipeline: download its assets, authenticate the checksum bundle with the independently retained signing key, check every distribution hash, and run the installed wheel's demo. A queued workflow or a green main run alone does not verify release publication.

Publication rejects missing, differently versioned or additional build archives before signing or creating a draft. Use a clean build output containing exactly the wheel, source distribution and Helm archive for the selected tag. `bash scripts/ci/checks/signing.sh` exercises setup and retry preservation offline; `bash scripts/ci/checks/release.sh` also requires those built archives and exercises signed publication through a local GitHub stub. CI runs both in the existing release-contract job.

The initial upstream signing key fingerprint (SHA-256 of DER SubjectPublicKeyInfo) is `c025b0ffd4e676db5710697b756ed9b4a46025966b26faface444f3318c8513f`. Compare against a separately trusted copy of this record; downloading a replacement key and fingerprint from the same untrusted release is insufficient.

## PyPI publication

Every Python package has an associated PyPI publication run. The broker's existing `CI` workflow owns preparation, upload and verification as dependent jobs. Tag releases publish after all checks and GitHub release verification pass. Ordinary pushes and PRs never upload to PyPI.

The organization owns the existing `PYPI_API_TOKEN` Actions secret. Grant this repository access to that selected-repository secret; do not create a duplicate token or place its value in files or commands. The publisher passes it directly to the pinned [PyPA publishing action](https://github.com/pypa/gh-action-pypi-publish) inside the `pypi` GitHub environment. Only that job references the credential. It has no source checkout, build steps or OIDC permission. PyPI attestations require trusted publishing and are disabled for this API-token path; the independently verified Cosign-signed GitHub archives remain the artifact trust source.

To publish an existing signed release, or recover a partial PyPI upload, dispatch from `main`:

```sh
gh workflow run ci.yml --repo astrivant/1password-agent-broker --ref main -f pypi_release=v0.1.0
```

This project currently accepts numeric `vMAJOR.MINOR.PATCH` release tags. Preparation requires an annotated tag with a GitHub-verified signature whose source is contained in main. It authenticates the complete GitHub release against the pinned independent key fingerprint, then exports exactly its wheel and source archive. Manual publication uses those original bytes; it does not rebuild the release with the workflow's newer source or move the tag.

The registry preflight permits missing files but rejects mismatched digests, unexpected filenames and yanked files. Identical existing files may be skipped on retry. A final verification job requires the full matching PyPI file set, downloads the exact wheel from PyPI without cache, compares it with the authenticated wheel, installs it in an isolated environment outside the checkout, and runs `agent-broker demo`. Newly uploaded files can precede public metadata visibility, so missing files receive six observations with sixty seconds of bounded backoff. Changed, unexpected or yanked files fail immediately. Missing credentials, registry errors, skipped/failed publication and files still missing after that wait remain visible failures. A failed or cancelled run can be dispatched again with the same tag. Never replace published bytes or treat HTTP 403, 429 or 5xx as an unregistered package.

Run `python -m unittest discover -s scripts/release/tests` for registry validation regressions. `bash scripts/ci/checks/release.sh` checks that only authenticated Python archives reach a fresh publication directory. Local runs and a green GitHub artifact release do not establish PyPI availability; record the actual publication run and test the registry install before claiming completion. The public [PyPI JSON API](https://docs.pypi.org/api/json/) supplies the version-specific file hashes.

## Downstream consumers

After verifying an authorized release, update known consumer repositories through focused PRs. Track each repository, previous and target version, affected installation/deployment paths, PR head, pipeline URLs and next review action. Reuse an existing upgrade PR. Discover consumers from maintained manifests, integrations and maintainer records; a repository search alone does not prove the inventory is exhaustive. Keep private consumer names and access details in their owning private records.

No external consumer inventory is currently verified by this repository. The integration surfaces to inspect are Python installations and lockfiles, MCP launch commands, Helm chart pins and values, and broker container image tags or digests. The chart requires an independently published broker image; the current release workflow does not publish one. Do not claim that shipping the chart upgrades or deploys an external service.

Exercise each consumer's installation and compatibility checks, then inspect all applicable pipelines for its current PR revision. Resolve failures and recheck after every correction; older green runs, queued jobs and unexpected skips do not establish success. Where CI uses a merge checkout, bind its evidence to the reviewed head and tested merge revision. Finish with links and actual outcomes for every known consumer, retaining unresolved upgrades as explicit handoffs. The maintainer still controls merging and deployment; honor an explicit request that they will monitor CI themselves.

## Chart validation

Use Helm 4.3.0, kubeconform 0.8.0, and Node.js for Bitnami's pinned README generator. The pre-commit hook derives parameter tables and a structural schema from annotated `values.yaml`; `scripts/helm/schema.py` adds deployment constraints and embeds the packaged authorization schemas. Edit these inputs and regenerate, rather than editing `values.schema.json` or parameter tables. CI checks generated-file drift and the README updater's `--check` mode.

`hypothesis-helm` 1.3.10 requires Python 3.13+ and pytest below 9. The isolated lock in `scripts/helm/` keeps that constraint out of the application's pytest 9 environment. Create its virtual environment with an absolute path so subprocess entry points retain the correct interpreter:

```sh
python3.14 -m venv "$PWD/scripts/helm/.venv"
VIRTUAL_ENV="$PWD/scripts/helm/.venv" poetry -C scripts/helm install
bash scripts/helm/check.sh
```

The chart job runs independently of Python tests and source builds, validates Kubernetes 1.30 schemas, exercises supported values with Hypothesis and hypothesis-helm, and compares source rendering with the packaged archive. Release-signing contract tests join the actual Python and chart artifacts afterward. The chart follows the public [Polyad chart layout](https://github.com/astrivant/polyad/tree/c446fa5f0dc8eaaec82b49e864e8ca86046c53d1/charts), using this project's top-level `helm/` convention: metadata, annotated values, generated schemas/README, grouped templates, NOTES, license, and concise reference overrides. No dependency lock is generated for an empty dependency set.

The [configuration reference index](../helm/1password-agent-broker/references/README.md) lists supported overlays. Keep each in `references/<name>/values.yaml` beside its README, using Bitnami `@section` and `@param` annotations for every override. `scripts/helm/generate.sh`, invoked by the existing Bitnami pre-commit hook, generates all reference parameter tables along with the chart's default table. The standard README hook maintains their contents. Add each configuration's link and purpose to the index; retain the chart README's reference section before generated parameters. Chart CI lints and renders every reference against the chart and Kubernetes schemas. Run `pre-commit run --all-files` and `bash scripts/helm/check.sh` after changing these sources, and review the generated output before staging.

PostgreSQL integration tests require an explicitly selected disposable database. Set `BROKER_TEST_POSTGRES=1` and native `PGHOST`, `PGPORT`, `PGDATABASE`, and `PGUSER` variables. Local synthetic containers may use `PGSSLMODE=disable`; production charts enforce certificate verification. CI provisions an isolated PostgreSQL 18.6 service for each Python-version test job. The tests create broker tables, use unique request IDs, and exercise cross-replica claims, cancellation, and recovery. Never point them at a production database.

## Runtime and client packages

`bash scripts/release/build.sh` builds the broker and its separately installable
client SDK. Their manifest versions must agree before a tag is accepted. The
root lockfile resolves the SDK from `packages/sdk` for development; published
metadata requires its exact registry version. `bash scripts/release/check-wheels.sh`
installs the SDK alone, checks that server/provider modules are absent, then
installs both wheels and runs the synthetic runtime demo outside the checkout.

Signed releases include both wheels and source distributions, the chart, source
provenance and a signed package inventory. The PyPI run authenticates those
archives, checks each project's existing file hashes, uploads missing files with
the existing organization credential, and independently verifies registry bytes.
It also supports retrying earlier runtime-only releases. Consumers should adopt
the SDK only after its registry publication has been verified.
