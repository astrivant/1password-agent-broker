# Operations and CLI

## Operator setup

Use a private directory, a broker-specific OS user, and Python 3.12+ (excluding 3.14.1). Installation includes the [1Password Python SDK](https://github.com/1Password/onepassword-sdk-python); no `op` executable is needed. SDK wheels support x86-64 and ARM64 on macOS and Linux, and x86-64 on Windows. Linux requires glibc 2.32+ and libssl3; the production container includes these dependencies.

Create a [1Password service account](https://www.1password.dev/service-accounts/get-started) with access only to the required vault. Set its token in the broker environment as `OP_SERVICE_ACCOUNT_TOKEN`; do not put the value in a policy, shell argument, Git, MCP config, or model prompt. The broker explicitly authenticates the SDK with that selected token; it does not use a desktop login session.

Provision a trusted TLS CA, a server certificate for the broker hostname, and a separate client certificate per workload/run. Certificates need the appropriate server/client extended key usages and current X.509 extensions. The demo's CA is synthetic and is never reused for deployment. Compute a client's policy fingerprint from DER:

```sh
openssl x509 -in workload.pem -outform DER | openssl dgst -sha256
```

Create `policy.json` below, replacing the fingerprint and synthetic identifiers. Exact 1Password references use IDs or unambiguous alphanumeric names. Paths have three components (`vault/item/field`) or four (`vault/item/section/field`), without query parameters. All keys are closed by the [packaged schemas](../pkg/agent_broker/resources).

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
