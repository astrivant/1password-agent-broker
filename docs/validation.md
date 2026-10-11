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

A canary check verifies specific output channels. It is not a proof that secrets are absent from all operating-system memory, swap, core dumps, or external services. No real 1Password account, OpenAI account, provider API, or production destination is used in these tests.

## Hosted checks

The single [CI workflow](https://github.com/astrivant/1password-agent-broker/actions/workflows/ci.yml) runs lint, Python tests, packaging/container smoke checks, and Trivy in parallel. Coverage reports and redacted security findings are attached to the run. Release publication waits for those checks and runs only for version tags in the upstream repository.

A green synthetic pipeline does not establish production readiness. Live 1Password authentication, organization-specific vault permissions, certificate issuance, ingress deployment, operational retention, and host isolation remain operator integration work.
