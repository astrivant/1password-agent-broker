# RFC #55 implementation review

Review date: 2026-10-13. Baseline: broker commit `326b373a8cd69265916cf270aca6a06b5cfbefbb` and the [restaged RFC at its supplied immutable revision](https://github.com/astrivant/product-research/blob/0e1ec91851bf76c6978011b73677c1b50cfe108c/rfcs/identity-scoped-1password-integration-review.md). The RFC's renewed decision remains pending. This code review does not approve a deployment or change the research decision record.

## Findings and changes

| Finding | Resulting contract | Evidence |
| --- | --- | --- |
| Authorization failed before identity attributes were assembled, leaving known callers unattributed on denials. | Resolve current certificate ownership first; retain identity/run/task attribution while excluding rejected input. | Denial tests cover expiry, cross-identity requests, and injected metadata. |
| Replay and cancellation paths omitted the actual terminal outcome, or always emitted `cancelled`. | Validate producer events against a closed schema and record actual outcome, replay status, and action. | Audit schema, replay, recovery, and cancellation regressions. |
| Cancellation reported success while a destination operation was already running. | Serialize submission and cancellation in SQLite; return uncertainty after admission and preserve completed results. | Event-coordinated race with one destination call, plus existing cancellation-during-resolution test. |
| Recovering a result required a current approval and unchanged execution policy. | Add read-only MCP inspection bound to the original request and identity snapshot. | Recovery after grant deletion and capability removal; forged requests and changed identities denied. |
| Identity/run attribution omitted task context. | Add optional operator-owned `task_id`; clients cannot forge it or transfer recovery authority across tasks. | Task-attribution and identity-snapshot regressions. |
| Malformed ports and unsupported destination characters could pass policy loading and fail during execution. | Reject them during configuration validation, before credential access. | Invalid port, authority, fragment, query, control-character, and non-ASCII destination cases. |
| Credential configuration required an alias for the standard service-account variable. | Default to `OP_SERVICE_ACCOUNT_TOKEN`, retaining explicit selectors for distinct accounts. | Contract validation and provider tests. |

The implementation stays independent of any particular knowledge platform. Identity source verification, certificate provisioning, and selection of an identity/run remain operator responsibilities. A prompt-level identity switch is not authentication. Existing provider and executor protocols remain the extension points; this review adds no arbitrary credential-read or network capability.

## SDK integration

The provider now uses the [official Python SDK at 0.4.1](https://github.com/1Password/onepassword-sdk-python/releases/tag/v0.4.1). The operator-selected service account authenticates an SDK client, which resolves exactly the policy-selected field. A short-lived worker preserves the existing ten-second timeout and bounds native session lifetime because this SDK revision has no public close method. The CLI binary and `serve --op` option are removed; [upgrade instructions](operations.md#sdk-upgrade) cover the command change and native runtime requirements.

Synthetic tests cover the SDK's real Python authentication/resolution adapters, native library loading, selected-account rotation, malformed worker input, timeout handling, and diagnostic redaction. Account authentication and vault permissions still require an authorized live integration check.

## Validation and acceptance

See [validation](validation.md) for current local results and the repository-wide acceptance inventory. Synthetic tests exercise actual localhost HTTPS/mTLS and an MCP stdio process, with no real provider account or destination. Existing reservations are retained when the additive context table is created; missing legacy evidence is not inferred.

Publication, hosted CI, container builds, and release verification need evidence for the actual delivered revision. Historical v0.0.1 evidence remains historical. Scoped CODEOWNERS rules route maintained broker paths to a verified repository administrator; they do not establish agent authorship or enforce branch protection.

## Remaining integration gates

- Real service-account permissions, credential isolation, downstream revocation, and usage-report correlation remain untested. Native 1Password permissions are not per-item isolation.
- Deployment must enforce agent/broker separation, certificate issuance, encrypted storage, retention, and bounded resource use. No production readiness claim follows from synthetic tests.
- HTTP framing failures before broker dispatch have no per-request durable audit. Events are OTel-shaped JSON, not an OTLP transport.
- Pending and uncertain work requires operator reconciliation. Automatic reclaim leases, distributed fencing, and independently replicated ledgers are unsupported.
- Release tooling assembles and verifies a draft before publication, checks exact versioned archive membership, and supports retrying signing setup with the same backup directory. The [release contract checks](development.md#release-signing) cover these paths with synthetic keys and a local host stub. A new real release and downstream consumer acceptance still require their own authorized publication and current-revision evidence.
- The Helm chart requires an independently published broker image and an external durable PostgreSQL service. This workflow builds test images but does not publish a container registry artifact or deploy a cluster.

The historical implementation and release are evidence for the bounded capability already delivered. Additional capabilities and a live pilot require their own selected operation, approval contract, and observable exit criteria.
