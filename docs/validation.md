# Validation

## Reproduce locally

```sh
poetry install
poetry run pytest -n 4 --cov=agent_broker --cov-report=term-missing
poetry run pre-commit run --all-files
poetry run agent-broker demo
```

The tests exercise real local HTTPS/mTLS and an actual MCP 2 stdio subprocess. Synthetic certificate fixtures meet current strict Python/OpenSSL verification rules; validation is not disabled to make the demo work.

## Evidence covered

| Boundary | Regression |
| --- | --- |
| Authentication | Distinct client certificates; absent certificate rejected; cross-identity capability denied. |
| Input authority | Unknown URL, method, header, vault, item, field, identity, reference, and instruction fields rejected before credential resolution. |
| Approval | Expired, revoked, and stale-policy grants rejected. |
| Credential lifetime | Rotation is observed on the next request; no credential is cached in agent state. |
| Official SDK | Actual authentication/resolution adapters with a synthetic core; offline native reference validation; scoped bootstrap rotation, worker input rejection, and redacted timeout/provider errors. |
| Replay | Completed requests return stored results; conflicting UUID reuse denied; pending reservations remain uncertain. |
| Cancellation | Before execution and during a provider lookup, synchronized using events rather than sleeps. |
| Unknown outcomes | Destination failure is not automatically resubmitted. |
| Audit | Export failure preserves durable state; storage failure before intent prevents credential access. |
| Redaction | Generated canaries absent from results, MCP output/stderr, command arguments, and the SQLite audit file. |
| Packaging | Wheel contains JSON schemas and SQL; container and installed CLI run the synthetic demo. |
| Release integrity | Temporary key generation, Cosign 3 bundle creation/verification, and package checksums; GitHub calls replaced by a local stub. |
| Identity/task attribution | Known callers remain attributable on denials; client metadata is rejected; task IDs are operator-owned. |
| Result inspection | Existing outcomes survive grant expiry/removal and capability removal; identity, revision, run, task, and request changes cannot inherit recovery authority. |
| Submission cancellation | SQLite submission admission races cancellation safely; an in-flight operation returns uncertainty and is not submitted twice. |
| Audit contract | Closed producer schema, terminal replay outcomes, isolated exporter attributes, and recoverable results after terminal audit failure. |
| Existing ledgers | Context-table creation preserves legacy reservations; unknown historical submission state is not inferred. |

A canary check verifies specific output channels. It is not a proof that secrets are absent from all operating-system memory, swap, core dumps, or external services. No real 1Password account, OpenAI account, provider API, or production destination is used in these tests.

## RFC #55 local review evidence

On 2026-10-13, the updated implementation passed 59 tests with four workers on Python 3.12.8, including real HTTPS/mTLS, an MCP stdio subprocess, and deterministic cancellation coordination. Measured line coverage was 77%; subprocess execution is exercised but is not included in that coverage measurement. The synthetic demo completed both approved operations, denied cross-identity and extra-field requests, replayed without resubmission, and made zero external provider calls.

All repository pre-commit hooks passed, including strict typing, docstring contracts, SQL, shell, and workflow validation. Wheel and source-distribution builds passed. The wheel was installed into a temporary target outside the checkout; its imported package location was verified and its demo passed using the locked runtime dependencies. Containers, the hosted Python matrix, Trivy, and a newly signed release were not run for this review.

The [review record](rfc-review.md) maps the implementation to the restaged RFC and identifies remaining integration gates. These are local results. Historical hosted and release evidence below does not validate this revision; live provider permissions and deployment isolation remain untested.

## SDK migration evidence

On 2026-10-13, the SDK migration passed all 74 tests on Python 3.12.8 with four workers and 78% measured line coverage, plus all repository hooks, Poetry lock validation, distribution builds, and the synthetic demo. SDK 0.4.1 installed from its source distribution and passed native reference validation on macOS ARM64 with Python 3.14.8. No real account authentication was attempted.

Both container targets built on Linux ARM64 with Python 3.14.8 and locked dependencies. The production image passed its demo with a read-only root, dropped capabilities, and no-new-privileges; native SDK reference validation also passed. Its installed wheel's isolated worker rejected malformed input with no output. The development container passed all 74 tests. Hosted CI, other container architectures, Trivy, and a new release were not exercised for this migration.

## Hosted checks

The single [CI workflow](https://github.com/astrivant/1password-agent-broker/actions/workflows/ci.yml) runs lint, Python tests, packaging/container smoke checks, and Trivy in parallel. Coverage reports and redacted security findings are attached to the run. Release publication waits for those checks and runs only for version tags in the upstream repository.

A green synthetic pipeline does not establish production readiness. Live 1Password authentication, organization-specific vault permissions, certificate issuance, ingress deployment, operational retention, and host isolation remain operator integration work.

## Repository acceptance inventory

Use this inventory when adding or changing a delivery path. Record the source revision, command or workflow, result, and any remaining gap. A facet is complete only when its relevant contract is exercised; use `not applicable` where a project deliberately has no such integration.

| Facet | Reproducible evidence |
| --- | --- |
| Local source and documentation | All pre-commit hooks; generated contents current; Markdown destinations checked. |
| Runtime behavior | Parallel pytest, supported Python versions, mTLS/MCP subprocesses, and bounded demo. |
| Installable artifacts | Build wheel/source distribution; install the wheel outside the checkout and run its demo. |
| Containers | Production and development builds; non-root, Tini, restricted runtime, and demo/test execution. |
| Main and PR triggers | Push and pull-request events in CI; record the actual run rather than assuming one event tests the other. |
| Security | Trivy vulnerability/secret scan, redacted reports, and documented trust boundaries. |
| Host configuration | `bash scripts/qa/github.sh OWNER/REPO`: actual metadata, Actions enablement, read-only default token, signing verification, signing-secret presence, active workflow, and enforced PR/CI protection with the documented administrator override. |
| Merge gate | `poetry run pytest -n 2 scripts/ci/tests`: successful prerequisites, failure/cancellation/skip rejection, malformed or incomplete results, and workflow/settings alignment. |
| Coverage publication | Main run publishes the measured report; read back the badge payload and confirm its commit is verified. |
| Signed release | A real tag run publishes artifacts; `bash scripts/qa/github.sh OWNER/REPO TAG` checks attachment completeness. Independently authenticate the signature, verify checksums, and test the downloaded wheel as described in [release signing](development.md#release-signing). |
| Signing setup recovery | `bash scripts/ci/checks/signing.sh`: real temporary Cosign keys, local host stub, partial-upload retries, unchanged key/password, repository binding and refusal of invalid or incomplete backups. |
| Consumer upgrades | After an authorized release, record known consumer version-update PRs and passing current-revision pipelines. No external consumer inventory is verified here; see [follow-through](development.md#downstream-consumers). |
| Live provider/deployment | Operator-authorized integration with real account permissions and infrastructure; synthetic CI does not cover this. |

GitHub settings are declared in `.github/settings.yml`; verify the host after applying them because the file has no effect without a settings integration. The audit script uses authenticated `gh` and `jq`, reads secret names only, and never retrieves secret values. It checks the [declared merge policy](development.md#pull-request-merge-policy) without changing protection rules. Coverage publication is a leaf job and writes only its derived branch, so it cannot cause recursive main builds.

## Initial release evidence

The first release, [v0.0.1](https://github.com/astrivant/1password-agent-broker/releases/tag/v0.0.1), was exercised through the [main pipeline](https://github.com/astrivant/1password-agent-broker/actions/runs/38126459312) and [tag pipeline](https://github.com/astrivant/1password-agent-broker/actions/runs/38126650838). Both passed. All local hooks and 29 Python tests passed before publication. The measured coverage payload was read back from its derived branch, and GitHub reported that generated commit as verified.

After publication, both distribution checksums passed and the release bundle verified against the separately retained maintainer key. The downloaded wheel was installed in a fresh environment and its demo ran outside the checkout: two healthy operations, replay without resubmission, rejected cross-identity access, and zero external provider calls.

This evidence describes that release. Live 1Password permissions, production deployment, and operator-selected branch protection still require separate acceptance. Changes to those contracts should add their own reproducible checks rather than inherit this release's result.

## HA and operational API review

Local review on 2026-10-13 exercised 85 tests on macOS/Python 3.12.8, including a disposable PostgreSQL 18.6 database, concurrent replica claims, shared cancellation, and recovery after grant revocation. Measured line coverage was 81%. On Linux ARM64/Python 3.14.8, the development container passed 81 runtime/database tests; four source-chart cases were intentionally exercised separately on the host with Helm.

Both container targets built from the updated lockfile. The production image passed the synthetic demo with a read-only root, private temporary filesystem, dropped capabilities, and no provider account. Helm 4.3.0 lint, Kubernetes 1.30 schema validation, twelve deterministic Hypothesis scale/feature examples, and thirteen hypothesis-helm whole-chart attempts passed. The packaged chart rendered identically to source. The chart generator uses its declared values schema; it does not expand inferred Kubernetes fields into an unsupported configuration surface.

Synthetic release checks verified Python/Helm checksums, downloaded draft bytes, source provenance, the independent signing-key fingerprint, and rejection of corrupted downloads and an untrusted key. These checks used temporary keys and a local GitHub stub. They did not publish a release or change repository signing secrets. The new terminal tag job requires the complete signed release even when its publisher was skipped.

No Kubernetes cluster deployment, database failover exercise, live 1Password account call, or production load benchmark was performed. Resource values are initial sizing guidance. The earlier v0.0.1 release does not cover these changes. Subsequent [hosted CI at revision 10a69f6](https://github.com/astrivant/1password-agent-broker/actions/runs/38378740687) passed lint, both Python versions, packaging, charts, security and the synthetic release contract. Publication jobs were correctly skipped for that PR run. See operations for ConfigMap revocation lag, PostgreSQL durability, and shutdown timeout limits.

## Maintainer workflow verification

The 2026-10-13 workflow review checked current project guidance against implementation and updated signing recovery, build selection and downstream handoff procedures. Local signing checks exercise first setup, repeated byte-preserving reuse, failure during the second secret upload, incorrect repository/password/public key/fingerprint, missing or partial backups, concurrent setup, linked paths, legacy empty-password keys, default paths and rejection of Git checkout storage.

Freshly built Python and Helm archives passed the synthetic signed-release contract. Extra and wrongly versioned archives were rejected before draft creation; untrusted keys and corrupted downloads remained rejected. All applicable pre-commit hooks and the two-identity synthetic demo passed. The broker runtime was unchanged, so the earlier runtime suite was not repeated. No real secrets were uploaded, signing keys rotated, release published or downstream deployed. Hosted results must be checked for the resulting PR revision separately from these local results.
