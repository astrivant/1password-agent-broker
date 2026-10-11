---
name: 1password-agent-broker
description: Develop, validate, and operate approved credential-backed capabilities without exposing credentials to agent context.
---

# 1Password Agent Broker

Read [SECURITY.md](SECURITY.md) and [operations](docs/operations.md) before introducing real credentials. Follow [development](docs/development.md) for the locked environment and checks.

## First run

Use `agent-broker demo` to verify the synthetic two-identity workflow. It creates only temporary local services and generated credentials. No account setup, model API, or secret values are needed.

## Existing deployment

Use the operator-provided MCP command and request identifiers. Call `execute_approved` with exactly `request_id`, `operation`, and `approval_id`. Retry the same IDs only to recover a recorded result. Treat `uncertain` as unresolved work requiring inspection, not authorization to create a new request. Use `cancel_approved` for cooperative cancellation.

Operator actions such as creating grants, changing policies, mounting tokens, issuing certificates, or accessing real vaults require explicit user authorization. Never request or print secret values. A user's permission to run the synthetic demo does not authorize those actions.

## Development

Keep identity claims bound to verified certificates. Do not bypass policy, approval, audit, or durable replay checks to fix an integration. Extend a named capability through models, JSON schemas, provider/executor interfaces, documentation, and meaningful regressions.

Before publication, run focused tests, full relevant pre-commit checks, and the synthetic demo. CI is the hosted check; do not describe local tests as hosted success. Preserve pending requests and records needed for safe recovery. Record verified implementation findings in [RFC #8](https://github.com/astrivant/product-research/pull/8) when its scope changes.
