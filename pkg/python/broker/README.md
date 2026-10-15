# 1Password Agent Broker

Run approved credential-backed capabilities without handing provider credentials
to an agent. This distribution owns the deployed service, its 1Password SDK
integration, durable ledger, CLI and MCP adapter.

<!-- toc -->

- [Install and verify](#install-and-verify)
- [Inputs](#inputs)
- [Development](#development)

<!-- /toc -->

## Install and verify

Requires Python 3.12 or newer, excluding 3.14.1.

```bash
python -m pip install 1password-agent-broker
agent-broker demo
```

The demo uses synthetic temporary services. See the
[project quick start](https://github.com/astrivant/1password-agent-broker#install-and-try-it)
for deployment and the
[client SDK](https://github.com/astrivant/1password-agent-broker/tree/main/pkg/python/broker_sdk)
for applications consuming the separately deployed key service.

## Inputs

| Input | Purpose |
| --- | --- |
| Policy and approval files | Operator-owned capabilities and current grants |
| TLS certificate, key and CA paths | Authenticate the broker and its callers |
| Ledger configuration | Durable request coordination through SQLite or PostgreSQL |
| Provider environment | Service-owned provider authentication |

The [operations guide](https://github.com/astrivant/1password-agent-broker/blob/main/docs/operations.md)
defines exact options, variables and authority boundaries. Credentials are never
part of the package or its demo inputs.

## Development

Both Python distributions live together under `pkg/python/`. Use the repository's
root Poetry environment and lockfile for development. The
[development guide](https://github.com/astrivant/1password-agent-broker/blob/main/docs/development.md)
covers builds, tests and signed publication.
