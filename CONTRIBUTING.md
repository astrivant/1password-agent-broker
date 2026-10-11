# Contributing

See [development](docs/development.md) for setup, checks, container profiles, and pinned tools. Keep changes focused on a concrete capability or contract.

Use typed attrs models, closed JSON schemas, strict mypy, Google-style multiline docstrings, Ruff, and package-local pytest tests. Keep SQL in `resources/sql/` and lint it separately. Explain non-obvious authority and lifecycle decisions with comments separated from surrounding code by blank lines.

Every credential-backed operation needs explicit input/output contracts and regressions for authorization, retries, cancellation, failure, and redaction. Use synthetic credentials and local services. Do not use real accounts in tests or CI.

Pull requests use **What**, **Why**, **How**, and **Validation**. Link the relevant contract and give the shortest reproduction command. Distinguish local validation, hosted CI, and live integration evidence. Report security issues through [private reporting](SECURITY.md).
