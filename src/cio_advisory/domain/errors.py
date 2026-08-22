"""Domain exceptions for the CIO Advisory Assistant (system B3).

Pure-Python exception hierarchy raised by the orchestration services. The domain
layer never imports Google Cloud, ADK, or any framework : these errors let callers
(API, CLI, the Agent Runtime adapter) react to domain-level failures without coupling
to any vendor SDK error type.
"""

from __future__ import annotations


class AdvisoryError(Exception):
    """Base class for all domain-level errors raised by B3 services."""


class GuardrailBlockedError(AdvisoryError):
    """Raised/flagged when the A1 guardrail blocks an input or output.

    An advisory briefing is consequential, so a blocked unsafe request must never
    yield a partial artifact : the AdvisoryService raises this rather than returning a
    half-built briefing that an RM might act on.
    """


class RetrievalEmptyError(AdvisoryError):
    """Raised when house-view retrieval (A2) returns no passages for a client.

    A briefing that cannot be grounded in any CIO house view is not fit to present;
    the service treats an empty governed-KB result as a hard error.
    """


class PortfolioUnavailableError(AdvisoryError):
    """Raised when the client's portfolio or profile cannot be loaded.

    Suitability cannot be assessed without the client's risk profile and holdings, so
    a missing portfolio is a hard error rather than a silently un-personalised briefing.
    """


class ClientAccessDeniedError(AdvisoryError):
    """Raised when a verified principal is not entitled to a client (object authZ).

    The advisory pipeline is keyed by ``client_id``, but a client id is NOT a capability:
    access is decided server-side from the VERIFIED
    :class:`~cio_advisory.domain.identity.Principal` against the client's owning tenant
    (see ``domain/entitlements.py``), never from the request body. A failed entitlement
    check maps to HTTP 403 at the API layer, and no portfolio/PII or briefing is produced.
    """
