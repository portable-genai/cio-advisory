"""Live house-view adapter (HouseViewRetrievalPort): real grounded market research.

The local profile grounds briefings on a fictional CIO corpus; a real demo cannot. This
adapter derives the day's investment themes from REAL published market commentary via
Gemini ``google_search`` grounding (the same research pattern as cdd-sow-research's live adverse
media): the model searches current public market-outlook coverage from major banks'
CIO offices and asset managers, and answers with structured themes, each carrying the
real source headline and URL, which become the briefing's citations.

Honesty note: these are research summaries of public commentary, not a governed
in-house CIO publication. Every citation names its real public source so a reviewer
can open it; the theme is only as good as that source.

The research result is cached on disk (default 6 h TTL) so one audience demo does one
research pass, not one per click. Google GenAI SDK imports are lazy: the module imports
without ``google-genai`` installed, and only a live retrieval needs it (plus
GOOGLE_CLOUD_PROJECT and application-default credentials).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import AssetClass, Citation, HouseView, SourceType, Stance

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google import genai

_LOG = logging.getLogger(__name__)

_STANCE_BY_VALUE = {s.value: s for s in Stance}
_ASSET_BY_VALUE = {a.value: a for a in AssetClass}

_DEFAULT_CACHE = Path.home() / ".cio_advisory" / "live-house-views.json"

_PROMPT = (
    "Search current public market commentary and investment outlooks published by "
    "major banks' CIO offices and large asset managers. Identify the {top_k} most "
    "prominent current investment themes. For each theme give: theme (a short label), "
    "stance (one of overweight, neutral, underweight - the prevailing published "
    "stance), asset_class (one of equity, fixed_income, cash, alternatives, "
    "real_assets, multi_asset), rationale (one or two sentences summarising the "
    "published reasoning), source_title (the real publication headline) and "
    "source_url (the real page you found it on). Only include themes you actually "
    "found in current published commentary; never invent a source.\n\n"
    'Return strictly JSON: {{"themes": [ ... ]}}.'
)


class LiveGroundedHouseViewAdapter:
    """Real market themes from grounded research, cited to their public sources."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache_path = Path(settings.live.research_cache_path or _DEFAULT_CACHE)
        self._cache_ttl = settings.live.research_cache_ttl_seconds
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # HouseViewRetrievalPort
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, str] | None = None,
    ) -> list[HouseView]:
        raw = self._cached_research(top_k)
        views = [v for v in (self._to_view(t, i) for i, t in enumerate(raw)) if v is not None]
        return views[:top_k]

    # ------------------------------------------------------------------ #
    # Research (grounded, cached)
    # ------------------------------------------------------------------ #
    def _cached_research(self, top_k: int) -> list[dict[str, Any]]:
        if self._cache_ttl > 0 and self._cache_path.is_file():
            age = time.time() - self._cache_path.stat().st_mtime
            if age <= self._cache_ttl:
                try:
                    themes = json.loads(self._cache_path.read_text(encoding="utf-8"))
                    if isinstance(themes, list) and themes:
                        return themes
                except (json.JSONDecodeError, OSError):
                    pass  # unreadable cache: fall through to a fresh research pass
        themes = self._research(max(top_k, 6))
        if themes and self._cache_ttl > 0:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(themes), encoding="utf-8")
            tmp.replace(self._cache_path)
        return themes

    def _get_client(self) -> genai.Client:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=self._settings.project_id,
                location=self._settings.region,
            )
        return self._client

    def _research(self, top_k: int) -> list[dict[str, Any]]:
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "the live profile's house-view research needs google-genai: "
                "pip install -e '.[gcp]' and set GOOGLE_CLOUD_PROJECT"
            ) from exc
        client = self._get_client()
        response = client.models.generate_content(
            model=self._settings.models.reasoning,
            contents=types.Content(
                role="user",
                parts=[types.Part.from_text(text=_PROMPT.format(top_k=top_k))],
            ),
            config=types.GenerateContentConfig(
                temperature=0.0,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = getattr(response, "text", "") or ""
        data = _parse_json(text)
        themes = data.get("themes")
        if not isinstance(themes, list):
            _LOG.warning("grounded research returned no parseable themes")
            return []
        return [t for t in themes if isinstance(t, dict)]

    # ------------------------------------------------------------------ #
    # Mapping
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_view(raw: dict[str, Any], index: int) -> HouseView | None:
        theme = str(raw.get("theme") or "").strip()
        source_url = str(raw.get("source_url") or "").strip()
        source_title = str(raw.get("source_title") or "").strip()
        if not theme or not source_url:
            # A theme without a real source is not evidence; drop it rather than
            # inventing provenance.
            return None
        stance = _STANCE_BY_VALUE.get(str(raw.get("stance") or "").lower(), Stance.NEUTRAL)
        asset = _ASSET_BY_VALUE.get(
            str(raw.get("asset_class") or "").lower(), AssetClass.MULTI_ASSET
        )
        rationale = str(raw.get("rationale") or "").strip()
        view_id = f"live-research-{index + 1:02d}"
        return HouseView(
            id=view_id,
            theme=theme,
            stance=stance,
            asset_class=asset,
            rationale=rationale,
            citation=Citation(
                source_id=view_id,
                source_type=SourceType.HOUSE_VIEW,
                title=source_title or theme,
                url=source_url,
                snippet=rationale[:280],
            ),
        )


def _parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON read: a grounded model answers with fences or preamble."""
    from ...domain._grounded import _extract_json_object

    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    snippet = _extract_json_object(stripped)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}
