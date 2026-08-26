"""Public-web grounding adapter via the Gemini API ``google_search`` tool (GroundingPort).

Secondary, cross-border evidence to corroborate (never replace) the primary CIO house
views. Gated by ``settings.grounding_enabled`` (SPEC §2) so no ``google_search`` traffic
leaves the tenancy when grounding is off. Because only one built-in tool is allowed per
agent, the agent layer isolates ``google_search`` in its own sub-agent; this adapter is the
synchronous equivalent used by the domain services.

The ``google.genai`` import is lazy so on-prem and test profiles import this module with no
GenAI SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import WebCitation


class GeminiGoogleSearchGroundingAdapter:
    """Ground a query against the public web via the Gemini ``google_search`` tool."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.grounding_enabled)

    def _get_client(self) -> Any:
        from google import genai

        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self._settings.project_id,
                # MODEL location, not the compute region.
                location=self._settings.models.location,
            )
        return self._client

    def ground(self, query: str, max_results: int = 5) -> list[WebCitation]:
        """Return public-web citations relevant to ``query`` (secondary evidence)."""
        if not self.enabled:
            return []
        from google.genai import types

        client = self._get_client()
        response = client.models.generate_content(
            model=self._settings.models.triage,
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )
        return self._extract_citations(response)[:max_results]

    @staticmethod
    def _extract_citations(response: Any) -> list[WebCitation]:
        out: list[WebCitation] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                if web is not None:
                    out.append(
                        WebCitation(
                            title=str(getattr(web, "title", "")),
                            url=str(getattr(web, "uri", "")),
                            snippet="",
                        )
                    )
        return out
