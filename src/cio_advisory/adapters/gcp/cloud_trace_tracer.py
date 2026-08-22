"""Cloud Trace tracer adapter (ObservabilityTracerPort).

Opens OpenTelemetry spans exported to **Cloud Trace** for the advisory reasoning loop, and
records token usage for FinOps. Message-content capture is OFF (SPEC §3) so client PII
never reaches a span; only structural attributes (span name, action, actor reference) are
attached.

The OpenTelemetry / Cloud Trace exporter imports are lazy so on-prem and test profiles load
this module with no SDK installed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from hex_service_kit.observability import TokenUsage

from ...config import Settings


class CloudTraceTracerAdapter:
    """Emit Cloud Trace spans + token-usage metrics (content capture OFF)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tracer: Any | None = None

    def _get_tracer(self) -> Any:
        if self._tracer is None:
            from opentelemetry import trace
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider()
            provider.add_span_processor(
                BatchSpanProcessor(CloudTraceSpanExporter(project_id=self._settings.project_id))
            )
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("cio-advisory")
        return self._tracer

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        """Context manager that opens a trace span for a unit of advisory work."""

        @contextmanager
        def _span() -> Iterator[None]:
            tracer = self._get_tracer()
            with tracer.start_as_current_span(name) as otel_span:
                # Structural attributes only; never message content (P-04).
                for key, value in attributes.items():
                    otel_span.set_attribute(key, value)
                yield

        return _span()

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        """Emit token/cost metrics for FinOps dashboards (no content)."""
        tracer = self._get_tracer()
        with tracer.start_as_current_span("llm.usage") as otel_span:
            otel_span.set_attribute("model", model)
            otel_span.set_attribute("input_tokens", usage.input_tokens)
            otel_span.set_attribute("output_tokens", usage.output_tokens)
            otel_span.set_attribute("thinking_tokens", usage.thinking_tokens)
