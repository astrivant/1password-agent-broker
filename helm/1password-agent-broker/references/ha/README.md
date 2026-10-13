# HA deployment reference

Use [values.yaml](values.yaml) as a small starting overlay for two broker replicas, clients in the `agents` namespace, and scrapers in `monitoring`. Unspecified settings inherit the chart defaults.

<!-- toc -->

- [Customize and install](#customize-and-install)
- [Parameters](#parameters)
  - [HA deployment](#ha-deployment)
  - [Client and monitoring access](#client-and-monitoring-access)

<!-- /toc -->

```sh
helm template broker ./helm/1password-agent-broker --namespace broker \
  --values ./helm/1password-agent-broker/references/ha/values.yaml
```

This renders an example for review. Before installation, publish and verify your broker image, provide an HA PostgreSQL writable-primary endpoint, and create the existing Secrets described in the [chart operations guide](../../README.md#operation). Kubernetes must have two schedulable nodes and a NetworkPolicy-capable CNI. The inherited empty policy denies all workloads.

## Customize and install

Put the verified image repository and digest, reviewed policy, and operator-issued approvals in `/private/broker/values.yaml`. Keep credential values in the existing Secrets. Apply the private overlay last so it overrides the reference:

```sh
helm upgrade --install broker ./helm/1password-agent-broker --namespace broker --create-namespace \
  --values ./helm/1password-agent-broker/references/ha/values.yaml \
  --values /private/broker/values.yaml
kubectl -n broker rollout status deployment/broker-broker --timeout=180s
```

The reference sets only the parameters below. See the [complete chart parameters](../../README.md#parameters) for inherited settings, and the [reference index](../README.md) for the configuration overview. The Bitnami pre-commit hook generates this table from the annotations in `values.yaml`.

## Parameters

### HA deployment

| Name               | Description                                                                     | Value                                          |
| ------------------ | ------------------------------------------------------------------------------- | ---------------------------------------------- |
| `replicaCount`     | Broker replicas spread across at least two nodes                                | `2`                                            |
| `image.repository` | Replace with your operator-published, verified broker image                     | `registry.example/team/1password-agent-broker` |
| `image.tag`        | Release tag matching the verified image; a private overlay may set image.digest | `0.1.1`                                        |

### Client and monitoring access

| Name                                | Description                                                | Value        |
| ----------------------------------- | ---------------------------------------------------------- | ------------ |
| `networkPolicy.clientNamespace`     | Namespace containing clients labelled broker-client=true   | `agents`     |
| `networkPolicy.monitoringNamespace` | Namespace containing scrapers labelled broker-monitor=true | `monitoring` |
