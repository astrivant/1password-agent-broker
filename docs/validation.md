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
| Host configuration | `bash scripts/qa/github.sh OWNER/REPO`: actual metadata, Actions enablement, read-only default token, signing verification, signing-secret presence, and active workflow. Branch protection and rulesets are reported for operator review. |
| Coverage publication | Main run publishes the measured report; read back the badge payload and confirm its commit is verified. |
| Signed release | A real tag run publishes artifacts; `bash scripts/qa/github.sh OWNER/REPO TAG` checks attachment completeness. Independently authenticate the signature, verify checksums, and test the downloaded wheel as described in [release signing](development.md#release-signing). |
| Live provider/deployment | Operator-authorized integration with real account permissions and infrastructure; synthetic CI does not cover this. |

GitHub metadata is declared in `.github/settings.yml`; verify the host after applying it because the file has no effect without a settings integration. The audit script uses authenticated `gh` and `jq`, reads secret names only, and never retrieves secret values. It reports policy state without silently changing protection rules. Coverage publication is a leaf job and writes only its derived branch, so it cannot cause recursive main builds.

## Initial release evidence

The first release, [v0.0.1](https://github.com/astrivant/1password-agent-broker/releases/tag/v0.0.1), was exercised through the [main pipeline](https://github.com/astrivant/1password-agent-broker/actions/runs/38126459312) and [tag pipeline](https://github.com/astrivant/1password-agent-broker/actions/runs/38126650838). Both passed. All local hooks and 29 Python tests passed before publication. The measured coverage payload was read back from its derived branch, and GitHub reported that generated commit as verified.

After publication, both distribution checksums passed and the release bundle verified against the separately retained maintainer key. The downloaded wheel was installed in a fresh environment and its demo ran outside the checkout: two healthy operations, replay without resubmission, rejected cross-identity access, and zero external provider calls.

This evidence describes that release. Live 1Password permissions, production deployment, and operator-selected branch protection still require separate acceptance. Changes to those contracts should add their own reproducible checks rather than inherit this release's result.
