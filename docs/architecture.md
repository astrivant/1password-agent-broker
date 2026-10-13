# Architecture

## Ownership and interfaces

The agent-facing MCP adapter holds only its workload certificate. It accepts `execute_approved`, `cancel_approved`, and `inspect_approved`, then sends closed JSON requests over mTLS to `/execute`, `/cancel`, and `/status`. It does not instantiate a 1Password provider. The remote broker derives identity from the verified client certificate, matches it to the operator policy, and re-reads approvals before execution.

The operator owns three distinct artifacts: policy, short-lived grants, and the durable SQLite ledger. A grant is for one exact request, not an interactive yes/no answer controlled by the agent. The CLI `approve` command is an operator action and must run outside the agent's authority. Concurrent grant-file writers must be serialized by the operator; atomic replacement prevents partially written files, not lost updates between two authors.

The `Provider` protocol resolves credentials inside the broker. `OnePasswordProvider` uses [the official `op read` command](https://www.1password.dev/cli/reference/commands/read), an exact field URI, a captured pipe, and a broker-only service-account environment. Provider errors never become tool text. The `Executor` protocol performs a capability with that credential. The current `HealthExecutor` sends a fixed HTTPS GET and returns only the response status.

## Request lifecycle

1. Authenticate mTLS and validate the closed request schema.
2. Match certificate, capability, exact grant, expiry, and policy hash.
3. Commit a reservation before reading any credential. A matching completed reservation replays its result; a pending reservation returns uncertainty.
4. Resolve the current credential, then recheck authorization and cancellation.
5. Commit `attempted` intent, then atomically admit submission only if cancellation has not won the ledger transaction. Submit the operation once.
6. Commit the bounded result while checking cancellation in the same transaction, then emit the terminal outcome. Export redacted events independently of durable storage. If terminal audit storage fails, surface `audit_failed`; the already committed result remains recoverable.

A reused UUID with different request data, principal, or policy hash is denied. SQLite immediate transactions serialize concurrent reservations across processes sharing the same local database. Do not use a network filesystem or separate per-replica ledgers to claim cluster-wide idempotence.

Cancellation is cooperative. Before submission it blocks work, including when it arrives during credential lookup. Cancellation and the submission marker are serialized through the shared ledger. Once admission is committed, cancellation reports uncertainty even if the destination call has not yet begun. A recorded terminal result takes precedence over a later cancellation. SIGTERM stops admission and drains existing bounded handlers. SIGKILL leaves pending reservations, which block accidental re-execution after restart.

Recovery uses a separate digest of the complete request, principal name, verified certificate, identity ID/revision, run, and optional task. It excludes the mutable capability list and policy hash, allowing inspection and cancellation of existing work after grant expiry or capability removal. It cannot authorize execution or transfer work to another identity snapshot. A still-present principal is required. The additive ledger table leaves legacy records intact without inventing missing attribution. No expiring leases or automatic reclamation are implemented; pending reservations remain pending until operators reconcile them.

## Audit contract

Durable events use OpenTelemetry-style JSON fields: nanosecond timestamps, severity, body, allowlisted attributes, and a service resource. The packaged `event.schema.json` rejects unknown attributes before storage or export. Attributes identify request, principal, identity revision, run, optional task, policy hash, approval, credential alias, destination class, and trace/span correlation where known. Active OpenTelemetry trace IDs are reused; otherwise the broker creates an independent correlation ID. These records are not an OTLP transport or an implemented trace exporter.

Events include requested, allowed, attempted, completed, denied, failed, uncertain, and cancelled. Terminal events record the actual result code, replay flag, and known HTTP status, including for inspection, conflicting replays, and cancellation. `action` distinguishes execution, cancellation, and status observations; `policy.sha256` identifies the policy used for that observation. Original execution policy remains in the earlier events correlated by request ID. Known certificate owners remain attributable when authorization or request-schema validation fails. Unknown identities and invalid requests never contribute arbitrary payload fields to the audit. HTTP parsing failures are rejected before dispatch and currently have no per-request durable event. Add ingress metrics outside this secret-free audit boundary if those counts are required.

## Extend a capability

Add an explicit typed operation variant, extend the packaged policy schema, implement an executor that validates its own bounded inputs and outputs, and add cross-identity, revocation, cancellation, timeout, and redaction regressions. Do not add a raw shell, generic URL, or arbitrary secret-read escape hatch. The intent is extensible authority that an owner can understand and revoke.

A reviewed knowledge collection can supply an identity ID and revision, but the broker does not fetch or trust a knowledge repository as authentication. Certificate provisioning and the operator policy establish that binding. No dependency on a particular identity platform or model provider is required.
