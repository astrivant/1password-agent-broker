# Operations and CLI

## Operator setup

Use a private directory, a broker-specific OS user, and Python 3.12+ (excluding 3.14.1). Installation includes the [1Password Python SDK](https://github.com/1Password/onepassword-sdk-python); no `op` executable is needed. SDK wheels support x86-64 and ARM64 on macOS and Linux, and x86-64 on Windows. Linux requires glibc 2.32+ and libssl3; the production container includes these dependencies.

Create a [1Password service account](https://www.1password.dev/service-accounts/get-started) with access only to the required vault. Set its token in the broker environment as `OP_SERVICE_ACCOUNT_TOKEN`; do not put the value in a policy, shell argument, Git, MCP config, or model prompt. The broker explicitly authenticates the SDK with that selected token; it does not use a desktop login session.

Provision a trusted TLS CA, a server certificate for the broker hostname, and a separate client certificate per workload/run. Certificates need the appropriate server/client extended key usages and current X.509 extensions. The demo's CA is synthetic and is never reused for deployment. Compute a client's policy fingerprint from DER:

```sh
openssl x509 -in workload.pem -outform DER | openssl dgst -sha256
```

Create `policy.json` below, replacing the fingerprint and synthetic identifiers. Exact 1Password references use IDs or unambiguous alphanumeric names. Paths have three components (`vault/item/field`) or four (`vault/item/section/field`), without query parameters. All keys are closed by the [packaged schemas](../pkg/python/broker/src/agent_broker/resources).

```json
{
  "version": 1,
  "principals": {
    "workload-a": {
      "certificate_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "identity_id": "reviewed-collection",
      "identity_revision": "reviewed-v1",
      "run_id": "run-001",
      "task_id": "task-001",
      "operations": ["service-health"]
    }
  },
  "credentials": {
    "service-token": {
      "reference": "op://vault-id/item-id/token"
    }
  },
  "operations": {
    "service-health": {
      "credential": "service-token",
      "url": "https://service.example/health",
      "kind": "health"
    }
  }
}
```

Initialize `approvals.json` with `{}` and restrict the directory to mode 0700 and private files to 0600. Keep it outside the checkout. Validate and start:

Use opaque identity, run, and task IDs suitable for the operator's audit storage. `task_id` is optional for existing policies; omission means task attribution is unavailable. `identity_revision` should identify an immutable reviewed revision or snapshot digest. The broker trusts the operator's binding and does not verify the underlying knowledge collection. `bootstrap_env` defaults to the official `OP_SERVICE_ACCOUNT_TOKEN` variable; an explicit selector is available for separate broker-held service accounts.

```sh
agent-broker config lint --policy /private/broker/policy.json --approvals /private/broker/approvals.json
agent-broker serve --policy /private/broker/policy.json --approvals /private/broker/approvals.json \
  --database /private/broker/audit.db --cert /private/broker/server.pem --key /private/broker/server.key \
  --client-ca /private/broker/ca.pem
```

The server defaults to `127.0.0.1:8443`. Choose `--host` and `--port` explicitly for another listener. `--destination-ca` trusts a private target service CA; omitting it uses system roots. Startup fails if required configuration is invalid. Server stdout contains secret-free audit events; errors go to stderr as generic operational messages.

## Approve and invoke

As the operator, approve one operation for up to one hour (300 seconds by default):

```sh
agent-broker approve --policy /private/broker/policy.json --approvals /private/broker/approvals.json \
  --principal workload-a --operation service-health --ttl 300
```

The command returns `request_id`, `operation`, and `approval_id`. These are safe to pass to the agent. Send exactly that object to `execute_approved`. Retain it unchanged when retrying a lost response. The grant file also includes `policy_sha256`, `expires_at`, and `revoked`; the command fills these fields. Serialize concurrent operator edits.

## MCP configuration

Register this stdio command in your MCP client's server configuration. The same command works independently of which model or agent client is used:

```sh
agent-broker mcp --url https://broker.example:8443 --ca /agent/ca.pem \
  --cert /agent/workload.pem --key /agent/workload.key
```

For [Codex MCP configuration](https://developers.openai.com/codex/mcp), a local server entry is:

```toml
[mcp_servers.credential_broker]
command = "agent-broker"
args = ["mcp", "--url", "https://broker.example:8443", "--ca", "/agent/ca.pem", "--cert", "/agent/workload.pem", "--key", "/agent/workload.key"]
```

No OpenAI API key is required by the broker. The MCP process must run without provider tokens and without access to the operator's files. Its workload private key is still an authority-bearing credential; scope and protect it accordingly.

All three tools return a structured `Result`: `state`, `code`, `status_code`, `replayed`, and `audit_warning`. Non-healthy outcomes are MCP tool errors. No remote body, header, vault value, or provider diagnostic is returned.

`inspect_approved` uses the same closed request schema and reads an existing reservation only. It never calls a credential provider, reserves work, or sends a destination request. Its result remains available after the grant expires or is revoked, and after the capability is removed from policy, provided the certificate, principal name, identity revision, run, and task binding remain unchanged. Unknown requests and mismatched bindings return `denied`.

Changing a conversational identity has no effect on the broker's certificate. Select an operator-provisioned workload for the intended identity/run. Removing its policy entry revokes both execution and recovery access; retain the ledger for operator investigation. Changing an identity revision, task, run, or certificate does not transfer old recovery authority to the replacement.

## Rotation, revocation, and recovery

- **Rotate a service credential:** update it in 1Password. The next approved request resolves the new value; the broker does not cache credentials.
- **Revoke a grant:** set `revoked` to true or remove it from `approvals.json`. This blocks requests that have not passed the final authorization check.
- **Revoke a workload:** remove its certificate mapping from policy. Issue new approvals after any policy edit, because the policy hash changed.
- **Cancel:** send the same request object to `cancel_approved`. Before submission it stops work. After the durable submission boundary it returns `uncertain`; if the outcome was already recorded, it returns that outcome. A cancellation acknowledgement never promises remote rollback.
- **Recover a lost response:** send the same request object to `inspect_approved`, even after its approval expires. Execution through `execute_approved` still requires current policy and a valid grant.
- **Uncertain result:** inspect the target and durable ledger. `inspect_approved` preserves uncertainty for pending requests. Only an operator can decide whether a new approved request is appropriate.
- **Restart:** reuse the same ledger. Deleting it or restoring a stale copy can remove replay protection.
- **Shutdown:** SIGINT/SIGTERM closes admission and drains bounded handlers. Force termination leaves durable pending reservations for inspection.

The broker does not retry provider or destination operations automatically. A failed provider result is replayable; after repairing the provider, issue a new reviewed grant. This avoids confusing transient transport failure with permission to repeat a remote side effect.

## SDK upgrade

Remove `--op` from existing `serve` commands and reinstall the broker with its locked SDK dependency. The executable-path option has been removed. Existing policy references, explicit `bootstrap_env` selectors, approvals, and ledgers keep their formats. Run `python -c 'from onepassword import Secrets; Secrets.validate_secret_reference("op://synthetic/item/token")'` in the installed environment to check native library loading without accessing an account. A real approved request is still required to validate service-account permissions.

## Existing ledger upgrade

Startup adds an independent `request_context` table without changing or deleting existing reservations or audit events. New reservations include a recovery binding and submission marker. Legacy reservations lack this evidence, so `inspect_approved` denies them. Their original execution replay checks still apply; cancelling a pending legacy reservation returns uncertainty. Use the operator ledger and destination evidence to reconcile legacy work. Do not delete reservations to enable recovery, and do not downgrade while requests are active: older brokers do not maintain the new submission marker.

## Kubernetes and high availability

The [Helm chart](../helm/1password-agent-broker/README.md) runs two broker replicas with a shared PostgreSQL ledger. It uses a ClusterIP Service, mandatory mTLS on port 8443, private monitoring on port 9090, node topology spread, a one-pod disruption budget, and a rolling update with zero unavailable pods and one surge pod. Provide at least two schedulable nodes with enough capacity for that extra pod. The chart creates no credential values, persistent volume, database, or cluster-wide RBAC.

Build and publish the production image to your registry from the reviewed source revision. The chart's default image is a placeholder; no broker image registry publication is currently automated. Pin the resulting digest in `image.digest`. Supply an external PostgreSQL service with a dedicated database and role, TLS verification, a fenced writable primary, and synchronous durable failover. Broker replica count cannot make a single PostgreSQL server highly available. Asynchronous failover that loses an acknowledged reservation can permit a duplicate effect; restoring a stale database has the same consequence. Retain reservations for as long as request identities may be retried, and plan audit retention and database capacity explicitly.

Provision these existing Kubernetes Secrets through your normal secret-management workflow:

| Values path | Required Secret keys | Purpose |
| --- | --- | --- |
| `secrets.tls` | `tls.crt`, `tls.key`, `ca.crt` | Broker server chain/key and trusted workload client CA. The server certificate must cover the hostname clients use, normally `broker-broker.broker.svc`. |
| `secrets.provider` | `OP_SERVICE_ACCOUNT_TOKEN` | Selected 1Password service account, readable only by broker pods. |
| `secrets.postgresql` | `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `ca.crt` | Native PostgreSQL connection settings and the database server CA. `PGHOST` must match its certificate. |
| `secrets.destinationCA` | `ca.crt` | Optional private destination CA. An empty name uses system roots. |

The database role needs schema/table creation on first startup and access to the broker's tables and identity sequence. Schema initialization is serialized with a transaction advisory lock; replicas then use atomic unique reservations and row locking around submission and cancellation. Pools have at most four connections per pod, including probe traffic, and at most sixteen waiting connection requests. Budget connections for replicas plus the rollout surge. Connection acquisition times out after two seconds; SQL statements and locks also have bounded waits. An unavailable ledger fails closed before credential use. Pending reservations after a crash remain uncertain on every replica; failover never automatically repeats them.

For a broker outside Kubernetes, use `--storage postgresql` without `--database` and supply the documented [PostgreSQL environment variables](https://www.postgresql.org/docs/current/libpq-envars.html). TLS defaults to `verify-full`; the broker requires a writable session. SQLite remains available for a single host with `--database`. Do not share SQLite through a network volume or give each replica its own replay database. There is no automatic SQLite-to-PostgreSQL data migration: quiesce execution and preserve old recovery access before changing stores; do not carry outstanding grants into an empty ledger.

Keep `/private/broker/values.yaml` private. It contains your image selection, Secret names, namespace selectors, and `configuration.policy` / `configuration.approvals` objects matching the JSON examples above. Provider and database secret values belong only in Secrets, never Helm values or release history.

```sh
helm lint ./helm/1password-agent-broker -f /private/broker/values.yaml
helm upgrade --install broker ./helm/1password-agent-broker -n broker --create-namespace \
  -f /private/broker/values.yaml --wait --timeout 180s
kubectl -n broker get pods -l app.kubernetes.io/instance=broker -o wide
kubectl -n broker rollout status deployment/broker-broker --timeout=180s
```

The values schema rejects unknown keys and invalid policy/grant shapes; the broker additionally validates semantic references at startup and before use. ConfigMaps contain policy metadata and authority-bearing grants, so restrict their writers and readers. Empty defaults deny all workloads. Client pods must have `broker-client: "true"` in `networkPolicy.clientNamespace`; scrape pods must have `broker-monitor: "true"` in `networkPolicy.monitoringNamespace`. The ingress policy requires a CNI that enforces NetworkPolicy. Kubelet probes use the private monitoring port. Egress restrictions are intentionally operator-owned because 1Password, database, DNS, and destination addresses vary; apply your cluster's supported egress controls.

### Configuration updates and revocation

ConfigMaps are the supported configuration mechanism. Both files are mounted as a projected directory, without `subPath`, and a configuration checksum triggers rollout on Helm upgrades. Kubernetes projection and rolling updates are eventually consistent: old and new policy generations can coexist temporarily. A successful API update alone is not proof that every broker has revoked authority. Keep grants short-lived. For immediate revocation, first isolate affected clients at the network layer, apply the change, wait for rollout and projection, and compare the mounted file hashes on every replica before restoring access.

```sh
kubectl -n broker get configmap broker-broker -o jsonpath='{.data.policy\.json}' | sha256sum
kubectl -n broker exec POD_NAME -- sha256sum /etc/broker/config/policy.json
```

Repeat for `approvals.json`. Use the operator's local files with `agent-broker approve`, then incorporate the generated grants into the next reviewed values update; do not run it against the read-only mounted ConfigMap. Serialize updates through one operator or GitOps owner. Any policy change invalidates old grants by policy hash. Secret environment values and TLS contexts are loaded at startup, so roll broker pods after rotating their bootstrap token, database login, or certificate material. A changed destination credential in 1Password is resolved on the next execution without restarting.

### Proposed CRD design

CRDs would improve discovery, validation, RBAC, and visible reconciliation status, but need a controller to become runtime configuration. They are a future design, not an installed chart feature. A proportionate design would use namespace-scoped `BrokerPolicy` and `BrokerGrant` resources. Policy carries the current closed capabilities and workload bindings; grants carry the existing exact-request, expiry, policy-hash, and revocation contract. Credentials remain Secret references or 1Password references. The controller validates semantic references, renders the same canonical files, and publishes `observedGeneration`, a configuration digest, and Accepted/Ready/Rejected conditions.

The controller must own conflict resolution, admission RBAC, expiration, and generation acknowledgement from every serving replica. Do not claim immediate revocation until the data plane can stop serving an older generation. Separate the CRD definitions into a versioned CRD chart with explicit schema/conversion upgrades and a controller compatibility contract; application chart upgrades must not casually remove CRDs or grants. A Kubernetes Lease for controller leadership would coordinate reconciliation, while PostgreSQL would still own request reservations. CRDs do not replace the replay ledger or establish exactly-once remote effects.

## Metrics, status, and lifecycle

Every `serve` process builds one Flask application. The authenticated capability listener and private monitoring listener share that application and use bounded Cheroot worker pools. The default monitoring address is `127.0.0.1:9090`; `--metrics-host` and `--metrics-port` configure it. Flask's development server is never used. Route access is bound to server-owned listener metadata and the actual verified TLS certificate, not forwarded headers or the HTTP Host value.

| Endpoint | Contract |
| --- | --- |
| `GET /metrics` | Prometheus exposition of queue sizes, active work, dependency timings, responses, admission rejections, lifecycle state, and available process CPU/RSS counters. No provider or database request during a scrape. |
| `GET /healthz`, `GET /livez` | Local JSON snapshot with `status`, a fixed `message`, `in_flight`, and `queues`. A draining process remains live. |
| `GET /readyz` | Validates current policy/grants and checks the writable ledger. Returns 503 when unavailable or draining. Never resolves a credential. |

The monitoring port does not serve `/execute`, `/cancel`, or `/status`. Keep it on a private network: operational data is intentionally unauthenticated there. Readiness performs database I/O; liveness and metrics do not depend on a healthy upstream service. Readiness does not prove that a 1Password account or a destination is reachable. Its fixed status message changes when a readiness check observes a dependency failure.

`broker_queue_size{queue="http"}` measures accepted connections waiting for a control worker, `observability` measures the monitoring listener's queue, and `database` measures pool waiters. These are owned userspace queues, not the kernel socket backlog. `broker_requests_in_flight` measures admitted handlers; `broker_phase_active` and `broker_phase_seconds` separate ledger, provider, and destination work. Response labels contain only fixed actions and result states, never workload IDs, URLs, references, or credential values.

The default execution capacity is eight, with two separate recovery slots; excess execution receives HTTP 503. Keep retries on the same request ID. SIGTERM/SIGINT marks the process draining, stops admission, drains handlers, joins listener workers, and closes the database pool. The chart allows 90 seconds for termination and the server gives HTTP workers 70 seconds to drain. Verify that budget under your real DNS, storage, and destination failure modes: socket timeouts are not a hard end-to-end deadline for slow DNS or trickled input. Forced termination leaves pending reservations uncertain; it is not a successful graceful drain.

## Likely bottlenecks and sizing

The expected first constraint is **provider and destination latency**, followed by dependency rate limits and concurrent SDK-worker memory. This is an architectural assessment, not a measured production capacity claim. The official SDK runs in one short-lived worker per resolution, so process startup adds CPU cost and each admitted lookup adds native-client memory. JSON/schema validation and TLS also consume CPU. PostgreSQL commit latency and contention on the same request ID can dominate with a distant database or heavy duplicate traffic.

| Observation | Likely constraint | Next action |
| --- | --- | --- |
| High provider/destination duration, low CPU, growing HTTP queue | Upstream latency or quota | Measure each dependency, colocate where useful, and tune concurrency within account limits. More pods do not increase a provider quota. |
| High ledger duration or database queue | Primary latency, contention, or pool pressure | Inspect PostgreSQL latency/locks and connection budgets before raising pool or replica counts. |
| Rising CPU and admission rejections | TLS, validation, or SDK startup | Profile representative policies and requests; increase CPU or replicas only with evidence. |
| RSS/cgroup memory rises with active provider lookups | Concurrent SDK native workers | Lower per-pod capacity or raise the measured memory budget. Watch OOM events. |

For steady work, throughput is approximately active concurrency divided by mean end-to-end latency until another limit intervenes. The chart's CPU/memory requests and limits are starting values, not benchmark results. Linux `process_*` metrics cover the broker parent process; use container/cgroup measurements to include SDK child processes. Measure p50/p95/p99 timings, queue depth, CPU throttling, and peak container memory with representative approved traffic before changing scale. The ledger and provider must sustain the combined load of all replicas and a rolling-update surge.

## Trusted service key operations

For opt-in encryption and signing custody, see [the service-only key API](key-service.md).
It uses explicit certificate-scoped grants and is separate from agent MCP tools.
