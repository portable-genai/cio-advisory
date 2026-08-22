"""Cloud Logging WORM audit adapter (AuditSinkPort).

Writes each already-redacted :class:`AuditEvent` to a **locked, WORM Cloud Logging bucket**
(retention ~7 years) in ``asia-southeast1`` (P-08). PII is removed at the domain boundary
(P-04) before the event reaches this adapter, so every log line is safe to persist. The
bucket lock is provisioned in Terraform (``logging_worm.tf``).

The ``google.cloud.logging`` import is lazy so on-prem and test profiles load this module
with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import AuditEvent
from ...domain.serialization import to_jsonable


class CloudLoggingAuditAdapter:
    """Append immutable, already-redacted audit records to a WORM log bucket."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log_name = settings.logging.log_name
        self._client: Any | None = None
        self._logger: Any | None = None

    def _get_logger(self) -> Any:
        from google.cloud import logging as cloud_logging  # lazy

        if self._logger is None:
            self._client = cloud_logging.Client(project=self._settings.project_id)
            self._logger = self._client.logger(self._log_name)
        return self._logger

    def record(self, event: AuditEvent) -> None:
        """Write an immutable, already-redacted audit record (WORM)."""
        logger = self._get_logger()
        payload = to_jsonable(event)
        logger.log_struct(
            payload,
            severity="NOTICE",
            labels={
                "resource": event.resource,
                "action": event.action,
                "decision": event.decision.value,
            },
        )
