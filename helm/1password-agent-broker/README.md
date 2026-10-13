# 1Password Agent Broker Helm chart

Run two certificate-authenticated broker replicas with a shared PostgreSQL replay ledger and a private operational endpoint.

<!-- toc -->

- [Operation](#operation)
- [Parameters](#parameters)
  - [Deployment](#deployment)
  - [Operator configuration](#operator-configuration)
  - [Private network access](#private-network-access)

<!-- /toc -->

```sh
helm upgrade --install broker ./helm/1password-agent-broker --namespace broker --create-namespace -f /private/broker/values.yaml
```

Requires Kubernetes 1.30+, a NetworkPolicy-capable CNI, two schedulable nodes with room for a surge pod, an operator-published broker image, an HA PostgreSQL writable-primary endpoint, and the existing Secrets listed below. Defaults have an empty deny-all policy and a placeholder image. They render for review; configure them before installation.

## Operation

Read the [operations guide](https://github.com/astrivant/1password-agent-broker/blob/main/docs/operations.md#kubernetes-and-high-availability) for Secret keys, durable failover, certificate names, ConfigMap propagation, metrics, and CRD plans. Set the image to your verified build. This chart does not install PostgreSQL or manage credentials, certificates, CRDs, or an operator.

```sh
helm lint ./helm/1password-agent-broker -f /private/broker/values.yaml
helm template broker ./helm/1password-agent-broker -n broker -f /private/broker/values.yaml > /private/broker/rendered.yaml
helm package ./helm/1password-agent-broker --destination dist
kubectl -n broker rollout status deployment/broker-broker --timeout=180s
```

The chart is packaged as a versioned `.tgz` alongside the Python release, covered by the signed checksum manifest. Verify the downloaded manifest against an independently trusted key before installing the archive. There are no chart dependencies, so no dependency lock is needed. Future dependencies must have a committed lock and use `helm dependency build` in validation and packaging.

## Parameters

### Deployment

| Name                        | Description                                                                   | Value                                     |
| --------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| `replicaCount`              | Broker replicas on distinct nodes; at least two for HA                        | `2`                                       |
| `image.repository`          | Operator-published image built from the matching source revision              | `registry.example/1password-agent-broker` |
| `image.tag`                 | Immutable release tag; use digest for stronger provenance                     | `0.1.0`                                   |
| `image.digest`              | Optional sha256 digest overriding the tag                                     | `""`                                      |
| `image.pullPolicy`          | Kubernetes image pull policy                                                  | `IfNotPresent`                            |
| `capacity`                  | Concurrent executions per pod; two additional slots are reserved for recovery | `8`                                       |
| `resources.requests.cpu`    | Initial CPU reservation; tune using measurements                              | `250m`                                    |
| `resources.requests.memory` | Initial memory reservation, including SDK workers                             | `256Mi`                                   |
| `resources.limits.cpu`      | CPU limit                                                                     | `2`                                       |
| `resources.limits.memory`   | Pod memory limit, including SDK workers                                       | `1Gi`                                     |

### Operator configuration

| Name                      | Description                                                                    | Value               |
| ------------------------- | ------------------------------------------------------------------------------ | ------------------- |
| `configuration.policy`    | Closed broker policy; credential references only, never values                 | `{}`                |
| `configuration.approvals` | Operator-issued grants keyed by approval ID                                    | `{}`                |
| `secrets.tls`             | Existing Secret with tls.crt, tls.key, and ca.crt for broker mTLS              | `broker-tls`        |
| `secrets.provider`        | Existing Secret with OP_SERVICE_ACCOUNT_TOKEN                                  | `broker-provider`   |
| `secrets.postgresql`      | Existing Secret with PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD and ca.crt | `broker-postgresql` |
| `secrets.destinationCA`   | Optional existing Secret with ca.crt for a private destination CA              | `""`                |

### Private network access

| Name                                | Description                                                                  | Value        |
| ----------------------------------- | ---------------------------------------------------------------------------- | ------------ |
| `networkPolicy.enabled`             | Restrict ingress to explicitly labelled peers; egress is operator-controlled | `true`       |
| `networkPolicy.clientNamespace`     | Namespace containing clients labelled broker-client=true                     | `default`    |
| `networkPolicy.monitoringNamespace` | Namespace containing scrapers labelled broker-monitor=true                   | `monitoring` |
