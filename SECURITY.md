# Security policy

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/astrivant/1password-agent-broker/security/advisories/new). Include a synthetic reproduction, affected commit, and the violated boundary. Do not publish credentials, vault identifiers, real audit databases, or unredacted provider output. The current main branch is supported during the alpha period.

## Trust boundaries

The broker process, its OS account, policy and approval files, certificate authority, database directory, and 1Password SDK worker and native libraries are trusted. Run the agent and broker as separate OS users or workloads. The agent must not read the broker's environment, filesystem, process memory, bootstrap token, or private server key. Anyone with a workload private key can exercise that workload's currently approved capabilities.

The broker uses mTLS certificate fingerprints, not client-provided identity claims. It validates closed request schemas and resolves only an exact operator-selected field. Grants bind an operation, request UUID, principal, expiry, and canonical policy hash. Policy changes invalidate outstanding grants. A second authority check after credential resolution catches revocation during that lookup; cancellation or revocation racing an already submitted request cannot undo it.

Read-only result inspection and cancellation of existing work use a separate exact-request and identity snapshot binding. They remain available after grant expiry or capability removal while the original principal, certificate, identity revision, run, and task are still configured. Neither operation grants execution authority. Removing the principal revokes recovery too. Conversational identity names or mode switches do not alter certificate authority. Legacy ledger records without recovery evidence remain subject to their original replay checks and operator reconciliation.

The implemented operation is an HTTPS GET with a bearer token. The endpoint is fixed by policy, certificate validation is required, redirects are not followed, and ambient HTTP proxies are ignored. Operators must trust the selected destination and protect its DNS and certificate authority. This is not a general-purpose SSRF proxy or a network sandbox.

## Sensitive data lifecycle

| Data | Location and lifetime | Responsibility |
| --- | --- | --- |
| 1Password bootstrap token | Broker environment, private worker input pipe, SDK/native memory until worker exit | Use a dedicated service account with minimum vault access; rotate and revoke through 1Password. The token is absent from worker arguments and environment. |
| Resolved credential | SDK/native memory, captured worker output pipe, broker memory, HTTPS request | Never returned to MCP, audit, or application stdout. The worker exits after one resolution; Python cannot guarantee memory zeroization. |
| Workload/server keys | Operator-managed private files | Restrict permissions, back up securely, and rotate certificates. Removing a fingerprint revokes new requests. |
| Policy and approvals | Operator-managed JSON, read for each request | Contains reference metadata and authority; protect against writes by agents. Serialize approval-file edits. |
| Audit and replay ledger | SQLite file, owner-only mode, private parent directory | Contains identity/run/reference aliases and outcomes, not credential values. Encrypt the underlying volume and backups when metadata is sensitive. |
| Synthetic demo | Private temporary directory and memory | Removed on normal exit. Hard termination or host failure can leave temporary synthetic files. |

Application-level encryption of the ledger is not implemented. Filesystem permissions do not replace encryption at rest or host isolation. Do not mount the database directory or provider environment into an agent container. Core dumps, swap, debugger access, and host logs require operator controls. This software cannot prevent a compromised broker, privileged host, or malicious approved destination from accessing a credential.

Keep the ledger for at least as long as grants and clients can retry request IDs. Losing or deleting it removes replay protection. Restore a backup only after revoking outstanding grants and reconciling in-flight requests. Pending or uncertain requests require operator investigation; never issue a new request ID merely to bypass uncertainty.

## Failure and audit behavior

Intent and an `attempted` event are durably stored before destination I/O. A failure to write that audit stops execution. Failure after submission returns an uncertain outcome. Optional stdout-export failure sets `audit_warning`, while the SQLite record remains authoritative. Safe error codes replace provider stdout/stderr and exception bodies. HTTP access logs are disabled so request text is not reflected into logs.

The server bounds body size, handler concurrency, socket timeouts, provider execution, and destination I/O. It drains owned threads on SIGTERM/SIGINT. It is not hardened as an internet-facing ingress: use a private network, ingress limits, and platform resource limits. One local SQLite ledger is the supported consistency boundary; independent replicas with independent ledgers are unsafe.

## Supply chain and CI

Poetry resolves pinned dependencies into a committed lockfile. CI installs that lock without updating it. Actions and container images are pinned to immutable revisions. Trivy scans the repository for secrets and dependency vulnerabilities; raw secret matches stay in temporary runner memory storage and are deleted, while only counts and vulnerability identifiers are published. Tests and demos use generated synthetic tokens, local services, and deterministic assertions, with no model or 1Password calls.

Tag releases sign checksums and attach the signature, public key, and SHA-256 fingerprint. A release's attached key alone does not prove identity: verify its fingerprint against an independently trusted maintainer record. See [release verification](docs/development.md#release-signing).
