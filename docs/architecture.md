# Architecture

## Ownership and interfaces

The agent-facing MCP adapter holds only its workload certificate. It accepts `execute_approved` and `cancel_approved`, then sends closed JSON requests over mTLS. It does not instantiate a 1Password provider. The remote broker derives identity from the verified client certificate, matches it to the operator policy, and re-reads approvals.

The operator owns three distinct artifacts: policy, short-lived grants, and the durable SQLite ledger. A grant is for one exact request, not an interactive yes/no answer controlled by the agent. The CLI `approve` command is an operator action and must run outside the agent's authority. Concurrent grant-file writers must be serialized by the operator; atomic replacement prevents partially written files, not lost updates between two authors.

The `Provider` protocol resolves credentials inside the broker. `OnePasswordProvider` uses [the official `op read` command](https://www.1password.dev/cli/reference/commands/read), an exact field URI, a captured pipe, and a broker-only service-account environment. Provider errors never become tool text. The `Executor` protocol performs a capability with that credential. The current `HealthExecutor` sends a fixed HTTPS GET and returns only the response status.

## Request lifecycle

1. Authenticate mTLS and validate the closed request schema.
2. Match certificate, capability, exact grant, expiry, and policy hash.
3. Commit a reservation before reading any credential. A matching completed reservation replays its result; a pending reservation returns uncertainty.
4. Resolve the current credential, then recheck authorization and cancellation.
5. Commit `attempted`, submit the operation once, and record a bounded result.
6. Commit the terminal outcome for retries. Export redacted events independently of durable storage.

A reused UUID with different request data, principal, or policy hash is denied. SQLite immediate transactions serialize concurrent reservations across processes sharing the same local database. Do not use a network filesystem or separate per-replica ledgers to claim cluster-wide idempotence.

Cancellation is cooperative. Before submission it blocks work, including when it arrives during credential lookup. After submission, the operation may have completed; the result is uncertain and no rollback is promised. SIGTERM stops admission and drains existing bounded handlers. SIGKILL leaves pending reservations, which block accidental re-execution after restart.

## Audit contract

Durable events use OpenTelemetry-style JSON fields: nanosecond timestamps, severity, body, allowlisted attributes, and a service resource. Attributes identify request, principal, identity revision, run, policy hash, approval, credential alias, destination class, and trace/span correlation. Active OpenTelemetry trace IDs are reused; otherwise the broker creates an independent correlation ID. These records are not an OTLP transport or an implemented trace exporter.

Events include requested, allowed, attempted, completed, denied, failed, uncertain, and cancelled. Unauthenticated or invalid requests never contribute arbitrary payload fields to the audit. HTTP parsing failures are rejected before dispatch and currently have no per-request durable event. Add ingress metrics outside this secret-free audit boundary if those counts are required.

## Extend a capability

Add an explicit typed operation variant, extend the packaged policy schema, implement an executor that validates its own bounded inputs and outputs, and add cross-identity, revocation, cancellation, timeout, and redaction regressions. Do not add a raw shell, generic URL, or arbitrary secret-read escape hatch. The intent is extensible authority that an owner can understand and revoke.

A reviewed knowledge collection can supply an identity ID and revision, but the broker does not fetch or trust a knowledge repository as authentication. Certificate provisioning and the operator policy establish that binding. No dependency on a particular identity platform or model provider is required.
