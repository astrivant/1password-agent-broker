---
name: 1password-agent-broker
description: Develop, validate, and operate approved credential-backed capabilities without exposing credentials to agent context.
---

# 1Password Agent Broker

Read [SECURITY.md](SECURITY.md) and [operations](docs/operations.md) before introducing real credentials. Follow [development](docs/development.md) for the locked environment and checks.

## First run

Use `agent-broker demo` to verify the synthetic two-identity workflow. It creates only temporary local services and generated credentials. No account setup, model API, or secret values are needed.

## Existing deployment

Use the operator-provided MCP command and request identifiers. Call `execute_approved` with exactly `request_id`, `operation`, and `approval_id`. Use `inspect_approved` with those same identifiers to recover existing state without execution authority, including after approval expiry. Treat `uncertain` as unresolved work requiring inspection, not authorization to create a new request. Use `cancel_approved` for cooperative cancellation; after submission it returns uncertainty or an already recorded outcome.

Identity, revision, run, and optional task attribution come from operator policy and verified certificates. A conversational identity switch does not change the MCP certificate or broker permissions. Have the operator bind a separate workload/run when changing identity; never supply attribution in tool arguments. Retiring a workload removes its certificate mapping. Existing ledger records remain available to the operator.

Operator actions such as creating grants, changing policies, mounting tokens, issuing certificates, or accessing real vaults require explicit user authorization. Never request or print secret values. A user's permission to run the synthetic demo does not authorize those actions.

## Development

Keep identity claims bound to verified certificates. Do not bypass policy, approval, audit, or durable replay checks to fix an integration. Extend a named capability through models, JSON schemas, provider/executor interfaces, documentation, and meaningful regressions.

Explain significant blocks, loops, and branches with concise intent comments, especially authorization, durable state transitions, cancellation, cleanup, and publication gates. Keep comments aligned with the implementation and preserve template whitespace semantics. Follow the comment and docstring conventions in [development](docs/development.md).

Before publication, run focused tests, full relevant pre-commit checks, and the synthetic demo. CI is the hosted check; do not describe local tests as hosted success. Preserve pending requests and records needed for safe recovery. Maintain the local [RFC review](docs/rfc-review.md) against [restaged RFC #55](https://github.com/astrivant/product-research/pull/55), keeping historical RFC #8 evidence separate from current validation. Posting review comments requires user authorization.

For HA, use the chart under `helm/1password-agent-broker/` and the shared PostgreSQL backend. Never deploy independent SQLite ledgers as replicas. Keep policy/grant values schema-validated and secret values in existing Secrets. CRDs remain a documented proposal. See the operations guide for revocation propagation and durable failover requirements.

Build HTTP routes through `APIBuilder` and attach metrics with `MetricsBuilder` to the same Flask application. Keep route handlers thin and dependency-free at composition time; the runtime owns production listeners, admission, draining, and storage cleanup. Run the chart checks in `scripts/helm/check.sh` when changing deployment contracts. Package the chart with Python release artifacts and verify downloads before publication.
