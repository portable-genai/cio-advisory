"""On-prem placeholder for ``ObservabilityTracerPort`` : the on-premise migration target.

One of the reversibility (P-02) migration placeholders: in the managed profile this port
binds to the Cloud Trace (OpenTelemetry) adapter; switching ``profile`` to ``onprem``
rebinds it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter. ``span`` raises rather
than silently returning a no-op context so the absence of real tracing is explicit on the
on-prem profile until a backend is wired in. Filling these bodies in is the only change
required; message-content capture stays OFF (P-04) when implemented.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from hex_service_kit.observability import TokenUsage

from ...config import Settings

_MESSAGE = (
    "On-prem ObservabilityTracerPort adapter is a migration placeholder; implement "
    "against your on-premise platform. Core domain logic is unchanged."
)


class OnPremTracerAdapter:
    """Placeholder tracer adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        raise NotImplementedError(_MESSAGE)

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        raise NotImplementedError(_MESSAGE)
