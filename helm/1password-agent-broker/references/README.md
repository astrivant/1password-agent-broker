# Chart configuration references

Choose a documented values overlay, then supply your private image and policy configuration. Each reference has its own README and annotated `values.yaml`; the Bitnami hook maintains its parameter table.

<!-- toc -->

- [Available configurations](#available-configurations)
- [Use a reference](#use-a-reference)

<!-- /toc -->

## Available configurations

| Configuration | Values | Intended use |
| --- | --- | --- |
| [HA deployment](ha/README.md) | [ha/values.yaml](ha/values.yaml) | Two broker replicas with clients in `agents` and scrapers in `monitoring`, using an operator-managed HA PostgreSQL endpoint. |

## Use a reference

References are partial overrides of the [chart defaults](../values.yaml), with placeholders for operator-owned infrastructure. Follow the selected README's prerequisites and commands. Pass your private overlay after the reference so your reviewed settings take precedence. The old `references/values-ha.reference.yaml` path is now `references/ha/values.yaml`.

See the [chart README](../README.md) for shared operations and the full parameter table. To add a supported configuration, create `references/<name>/values.yaml` and `README.md`, annotate each override for Bitnami, and add its description here. The existing documentation hook discovers all such pairs; chart CI lints and renders every reference against the chart schema and Kubernetes resource schemas.
