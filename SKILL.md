---
name: 1password-agent-broker
description: Develop, validate, and operate approved credential-backed capabilities without exposing credentials to agent context.
---

# 1Password Agent Broker

Read [SECURITY.md](SECURITY.md) and [operations](docs/operations.md) before introducing real credentials. Follow [development](docs/development.md) for the locked environment and checks.

## Use without a source checkout

The [public skill](https://github.com/astrivant/1password-agent-broker/blob/main/SKILL.md) can be read without cloning this repository. Resolve its relative documentation links within the same repository and revision. `main` follows development; use the matching release tag or source revision when checking version-specific behavior.

The published package provides the demo, broker server, and MCP adapter without a source checkout. On a host with Python 3.12+ excluding 3.14.1, follow the [quick start](README.md#install-and-try-it) to install it and run `agent-broker demo`. The demo runs on that host. For an existing deployment, the host running the stdio MCP adapter needs the installed package, broker network access, and operator-provided configuration and workload certificates. Reading this URL alone does not connect an agent to a broker; follow [MCP setup](docs/operations.md#mcp-configuration).

Source edits, repository hooks and scripts, container builds, and chart development require a local checkout and the [development prerequisites](docs/development.md). Installing an already verified release chart archive does not require a clone; follow the [chart operations](helm/1password-agent-broker/README.md#operation). Select the workflow for the task before requesting a checkout.

## Start source work from current guidance

Inspect the worktree, index, remote branch and current PR before editing. Fetch the intended remote, review incoming changes, and fast-forward when possible. Preserve user edits and published history; resolve divergence from both sides' intended behavior rather than resetting or force-pushing.

Reread changed project instructions, tooling and lockfiles. Reassess applicable maintained skills and prior verified findings whenever this project is revisited. Apply them to concrete contracts and checks; document remaining gaps without importing unrelated workflows or private guidance into the repository. Reading a new skill does not establish that the existing implementation already follows it.

## First run

Use `agent-broker demo` to verify the synthetic two-identity workflow. It creates only temporary local services and generated credentials. No account setup, model API, or secret values are needed.

## Existing deployment

Use the operator-provided MCP command and request identifiers. Call `execute_approved` with exactly `request_id`, `operation`, and `approval_id`. Use `inspect_approved` with those same identifiers to recover existing state without execution authority, including after approval expiry. Treat `uncertain` as unresolved work requiring inspection, not authorization to create a new request. Use `cancel_approved` for cooperative cancellation; after submission it returns uncertainty or an already recorded outcome.

Identity, revision, run, and optional task attribution come from operator policy and verified certificates. A conversational identity switch does not change the MCP certificate or broker permissions. Have the operator bind a separate workload/run when changing identity; never supply attribution in tool arguments. Retiring a workload removes its certificate mapping. Existing ledger records remain available to the operator.

Operator actions such as creating grants, changing policies, mounting tokens, issuing certificates, or accessing real vaults require explicit user authorization. Never request or print secret values. A user's permission to run the synthetic demo does not authorize those actions.

## Development

Keep identity claims bound to verified certificates. Do not bypass policy, approval, audit, or durable replay checks to fix an integration. Extend a named capability through models, JSON schemas, provider/executor interfaces, documentation, and meaningful regressions.

Use the maintained vendor SDK where it supports the integration. Verify official SDK capabilities and runtime compatibility before introducing a CLI or process wrapper for a new SaaS backend. The existing 1Password worker isolates the official SDK; it is not an `op` CLI adapter.

Explain significant blocks, loops, and branches with concise intent comments, especially authorization, durable state transitions, cancellation, cleanup, and publication gates. Keep comments aligned with the implementation and preserve template whitespace semantics. Follow the comment and docstring conventions in [development](docs/development.md).

Before publication, run focused tests, full relevant pre-commit checks, and the synthetic demo. CI is the hosted check; do not describe local tests as hosted success. Preserve pending requests and records needed for safe recovery. Maintain the local [RFC review](docs/rfc-review.md) against [restaged RFC #55](https://github.com/astrivant/product-research/pull/55), keeping historical RFC #8 evidence separate from current validation. Posting review comments requires user authorization.

Before any handoff or work pause, run `pre-commit run --all-files` against the final working state, including reviewed new files. The README contents hook must cover root and nested READMEs. Inspect generated changes and rerun until the hooks pass without further edits. Report a remaining failure or unavailable check explicitly; an earlier pass does not validate later changes, and a pause does not grant permission to stage unrelated work.

Keep the pinned, always-run CODEOWNERS hook enabled when changing ownership rules or repository paths. It checks syntax, duplicate patterns and unmatched paths; verify owner eligibility separately on GitHub. See [CODEOWNERS validation](docs/development.md#codeowners-validation).

For HA, use the chart under `helm/1password-agent-broker/` and the shared PostgreSQL backend. Never deploy independent SQLite ledgers as replicas. Keep policy/grant values schema-validated and secret values in existing Secrets. CRDs remain a documented proposal. See the operations guide for revocation propagation and durable failover requirements.

Keep each chart configuration reference in `references/<name>/` with annotated `values.yaml` and a README generated by the existing Bitnami hook. List each reference and its purpose in `references/README.md`, linked before generated parameters in the chart README. Keep overrides small, update the index when adding a configuration, and run the chart checks so every documented reference renders against the supported schemas.

Build HTTP routes through `APIBuilder` and attach metrics with `MetricsBuilder` to the same Flask application. Keep route handlers thin and dependency-free at composition time; the runtime owns production listeners, admission, draining, and storage cleanup. Run the chart checks in `scripts/helm/check.sh` when changing deployment contracts. Package the chart with Python release artifacts and verify downloads before publication.

## Publication and follow-through

Keep `ci.yml` as the pipeline entry point and implement cohesive stages in reusable
`stage-*.yml` workflows. Pass the immutable source revision explicitly, retain
independent validation jobs, and keep the stable merge gate in the entry workflow.
Preserve the tag verifier and authenticated PyPI retry path when changing stage
boundaries. See [CI stage contracts](docs/development.md#ci-stage-contracts).

Maintain `.github/settings.yml` and the [PR merge policy](docs/development.md#pull-request-merge-policy) together. Normal merges require one independent approval and the stable `PR quality gate`, covering every required CI producer. Verify host protection with `scripts/qa/github.sh`; a committed settings file does not establish enforcement. Administrator bypass requires explicit maintainer approval for that merge and passing CI. Do not infer override permission from the ability to administer the repository.

Use signed commits and verify the pushed revision on the host. Keep the PR body current with the purpose, behavior, compatibility constraints, exact validation revision, and next review action. Give a brief contributor/contact note, and distinguish authorship, publishing and approval. Read review notes before acting on an ambiguous hold; consult the responsible maintainer when those notes do not resolve it.

Follow [release signing](docs/development.md#release-signing) for explicit key setup, exact artifact selection and downloaded-release verification. A tag or successful build alone is not a verified release. Do not merge, deploy, rotate keys or create credentials merely to complete a source review.

Every Python package has a PyPI publication run. This project's CI publishes its already authenticated Python release archives with the organization's existing `PYPI_API_TOKEN`, then compares PyPI file digests and runs the installed demo outside the checkout. Follow [PyPI publication](docs/development.md#pypi-publication) for release retries and first publication; preserve immutable tag and artifact bytes. An existing GitHub release is not evidence that a package is available on PyPI.

After an authorized release, promptly open upgrade PRs for known downstream consumers and follow their current-revision pipelines through success. Include installation paths and lockfiles in dependency updates; fix ordinary upgrade failures and recheck the new revision. Keep missing access, compatibility blockers and user-owned handoffs explicit. See [consumer follow-through](docs/development.md#downstream-consumers). An explicit request that the user will watch CI takes precedence; PR creation does not imply merge authority.

Before handing work back, review applicable project contracts with actual evidence, exclusions and remaining actions. Preserve confirmed defects as concise regression-backed findings for future work. Report implementation, local validation, remote publication, hosted CI and deployment as separate outcomes.
