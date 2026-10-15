# Service-only key custody

The opt-in `/crypto` endpoint gives trusted controllers wrapping, unwrapping and
ciphertext-signing operations while the broker retains long-lived private keys.
It implements the key boundary proposed by [protected-state RFC 74](https://github.com/astrivant/product-research/pull/74)
and [native-storage RFC 75](https://github.com/astrivant/product-research/pull/75).
It is separate from the agent MCP capability surface. An agent certificate has no
cryptographic grant unless an operator explicitly enrolls it.

## Configuration and trust

Pass `agent-broker serve --crypto-policy /operator/crypto.json` alongside the
existing server options. The Helm equivalents are `crypto.enabled` and
`crypto.policy`. The default is disabled. The packaged
[closed policy schema](../pkg/agent_broker/resources/crypto-policy.schema.json)
is authoritative; unknown fields are rejected.

`keys` maps generation UUIDs to `credential.reference`, `kind` and
`public_sha256`. References resolve through the existing official 1Password SDK.
Store base64-encoded PKCS8 DER in the referenced field: RSA (3072 through 8192 bits)
for `wrapping`, or Ed25519 for `signing`. The pin is SHA-256 of the public key's DER
SubjectPublicKeyInfo. Verify pins through an independent trusted channel. Never
put private keys, service account tokens or raw data keys into Helm values, policy
files, arguments, diagnostics or Git.

`grants` maps grant UUIDs to the verified client-certificate fingerprint, tenant,
identity, task, authority, policy revision, permitted actions, key generations,
expiry and explicit record IDs. Every identifier is an opaque canonical UUID.
`all_records: true` explicitly broadens the record scope within that identity;
it defaults to false. `revoked: true` blocks subsequent authorization checks.
The policy is reloaded before key access, after SDK resolution and before result
release. A changed policy snapshot invalidates an in-flight operation.

The broker authenticates workload certificates directly with TLS 1.3. Proxy
identity headers do not grant access. Monitoring listeners cannot route key
operations. Deploy the broker under independent administration with restricted
vault, network and policy-writing access. Its mounted ConfigMap update delay is
part of the revocation propagation window. File-backed grants alone do not provide
a strongly consistent cross-service authority registry or restore fencing.
Controllers must enforce their registry epoch and current grants before accepting
writes and releasing decrypted results. Do not claim linearizable revocation from
a ConfigMap rollout.

## SDK contract

Use `agent_broker.crypto.client.CryptoClient` with the broker HTTPS origin, trusted
CA and workload certificate/key paths. `invoke(Request(...))` returns bytes or a
fixed `ProviderFailure`. The request carries a fresh operation UUID, grant UUID,
action, generation UUID, immutable `Binding`, current task/authority/policy UUIDs
and canonical base64 payload. Access revisions are checked on every call but are
excluded from permanent associated data so authorized historical recovery survives
a grant change. The binding
includes the immutable record/revision UUID, its kind, and independently versioned
schema, codec, hash and envelope contracts.

| Action | Input | Output |
| --- | --- | --- |
| `wrap` | Fresh 32-byte data key | RSA-OAEP-SHA256 ciphertext bound to the complete context |
| `unwrap` | Wrapped key under the same context | Transient 32-byte data key, only to the authorized service |
| `sign` | SHA-256 of final ciphertext envelope bytes | Domain-separated Ed25519 signature bound to that context |
| `public` | Empty bytes | Public DER key; verify against an independently held pin |

Signatures cover `signature_input(request, ciphertext_digest)`. Verify them before
decrypting. Data keys permit the trusted controller to encrypt/decrypt records in
memory; they are never exposed through MCP. Python does not promise reliable
zeroization of immutable objects. Memory-backed temporary storage, disabled swap,
core-dump restrictions, bounded buffers and process isolation remain deployment
requirements, not guarantees supplied by deleting a Python variable.

The service persists only the opaque request/grant IDs, a request-binding digest
and bounded audit outcome. It never stores request payloads, returned data keys,
signatures or private keys in the ledger. Exact completed requests may recompute
pure operations after reauthorization. RSA wrapping uses randomness and need not
reproduce identical bytes. Changed inputs under an existing request ID are denied;
an unfinished claim is unavailable. The client performs no implicit retry. Resolve
controller commit outcomes through its durable receipt before creating a new
request. A key operation alone is not an accepted storage mutation.

## Rotation and recovery

Create a separate generation and independently review its public pin before
changing grants. Wrapping-key rotation unwraps and rewraps an existing data key;
content rotation decrypts and reseals with a new data key and nonce; signing-key
rotation authenticates final ciphertext with a new signer. Keep these operations
separate. Preserve old verification pins and recovery grants for retained history.
The endpoint neither creates real vault keys nor retires old generations.

Every replica needs a consistent operator policy and the existing shared durable
ledger. Independent SQLite ledgers do not provide HA. A provider, policy or audit
failure withholds the result. Restore the audit frontier and operator authority
before admitting requests after recovery; restoring a stale policy backup must
not silently re-enable revoked access.

## Validation boundary

Synthetic tests cover scope substitution, independent signing, tampering,
revocation during key resolution, retry binding and real mTLS client/server
transport. They use generated keys and the in-memory provider. They do not prove
live 1Password availability, production revocation latency, PostgreSQL failover,
key retirement or the security of an operator's deployment.
