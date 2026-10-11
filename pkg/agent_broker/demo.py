"""
Run a bounded synthetic demonstration without 1Password, a model, or external services.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from agent_broker.contracts import data, encode
from agent_broker.testing.scenario import scenario


def run() -> dict[str, object]:
    """
    Demonstrate two identities, replay safety, and rejection before credential access.

    Returns:
        dict[str, object]: Safe evidence summary suitable for terminal or CI output.

    Raises:
        RuntimeError: An expected security or execution invariant fails.
    """
    with TemporaryDirectory(prefix="agent-broker-demo-") as directory, scenario(Path(directory)) as fixture:
        alpha, bravo = fixture.request(), fixture.request("bravo")
        first = fixture.clients["alpha"].call(data(alpha))
        second = fixture.clients["bravo"].call(data(bravo))
        replay = fixture.clients["alpha"].call(data(alpha))
        crossed = fixture.clients["alpha"].call(data(bravo))
        injected = fixture.clients["alpha"].call({**data(alpha), "url": "https://untrusted.invalid"})
        summary = {
            "identities": 2,
            "approved_operations": [first.code, second.code],
            "replay_without_resubmission": replay.replayed and len(fixture.destination_calls) == 2,
            "cross_identity_denied": crossed.state == "denied",
            "extra_fields_denied": injected.state == "denied",
            "provider_resolutions": len(fixture.provider.calls),
            "external_provider_calls": 0,
        }
        output = encode(summary)
        stored = (fixture.root / "audit.db").read_bytes()
        if (
            first.code != "healthy"
            or second.code != "healthy"
            or not all(
                [
                    summary["replay_without_resubmission"],
                    summary["cross_identity_denied"],
                    summary["extra_fields_denied"],
                ]
            )
        ):
            raise RuntimeError("Synthetic demonstration failed")
        if any(token.encode() in output or token.encode() in stored for token in fixture.provider.secrets.values()):
            raise RuntimeError("Synthetic secret exposure detected")
        return summary
