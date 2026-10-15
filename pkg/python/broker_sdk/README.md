# 1Password Agent Broker SDK

A typed, bounded mTLS client for the separately deployed
[1Password Agent Broker](https://github.com/astrivant/1password-agent-broker).
Service clients install this distribution to request key operations without
installing the broker server, its 1Password integration or its database adapters.

<!-- toc -->

- [Install](#install)
- [Inputs and authority](#inputs-and-authority)
- [Compatibility and failures](#compatibility-and-failures)
- [Development and publication](#development-and-publication)

<!-- /toc -->

## Install

Requires Python 3.12 or newer, excluding 3.14.1. After the SDK release is published:

```bash
python -m pip install 1password-agent-broker-sdk
```

Import `CryptoClient`, `Binding` and `Request` from `agent_broker_sdk`. Construct
`CryptoClient(url, ca, cert, key)` using operator-provided paths, then pass a typed
`Request` to `invoke`. The returned bytes may contain a transient data key: keep
them inside the trusted service and out of logs, agent context and persistent
storage. See the [key service contract](https://github.com/astrivant/1password-agent-broker/blob/main/docs/key-service.md) for request
fields and operator setup.

## Inputs and authority

| Input | Meaning |
| --- | --- |
| `url` | Fixed HTTPS broker origin; no path, credentials, query or fragment |
| `ca` | Path to the trusted broker certificate authority |
| `cert`, `key` | Paths to the workload's scoped TLS certificate and private key |
| `Request` | Opaque grant, task, authority, policy and key identifiers, immutable record binding and operation payload |

The client holds no 1Password service token or custodial private key. The broker
checks current policy for each operation. SDK validation checks wire shape; it
does not grant permission. A small dependency set does not limit the authority
of an overprivileged certificate.

## Compatibility and failures

The SDK owns protocol-version-one models and schemas. The server imports these
same contracts. Its original `agent_broker.crypto.client.CryptoClient` import
remains available with the original runtime exception boundary.

The SDK requires TLS 1.3, verifies server identity, presents a client certificate,
limits messages to 4 KiB and decoded results to 1 KiB, and uses a 30-second socket
timeout. It raises a fixed `BrokerError` without reflecting payloads or policy.
Calls have no implicit retry; callers retain the exact request UUID and payload
when explicitly recovering a request. No admin, provider or policy-edit API is
included.

## Development and publication

The repository's root lockfile owns the SDK test environment. Both distributions
use the same release version and immutable source tag. CI tests the SDK's isolated
wheel and real mTLS transport before publishing signed archives and both PyPI
packages. The SDK has no server dependency; the server depends on its exact SDK
version. Local Poetry development resolves that dependency from this directory,
while wheel metadata names the versioned registry distribution.
