"""Root ADK agent for the B3 CIO Advisory Assistant, hosted on Agent Runtime.

This is the agent the Gemini Enterprise Agent Platform **Agent Runtime** (ex-Agent Engine)
hosts. It wires together:

* the three domain-capability :class:`FunctionTool` wrappers (``agent.tools``),
* the isolated ``google_search`` grounding **sub-agent** as an ``AgentTool``
  (``agent.grounding_agent``; one built-in tool per agent : SPEC §3),
* the defense-in-depth model-boundary **callbacks** (redact + guardrail + audit;
  ``agent.callbacks``), and
* the reasoning model ``settings.models.reasoning`` (``gemini-3.5-flash``) at
  ``thinking=high`` (SPEC §3).

ADK convention is honoured two ways: the module exposes a ``root_agent`` attribute (what
ADK / ``adk web`` / Agent Runtime discover by default) **and** a ``build_root_agent(settings)``
factory for explicit, test-friendly construction.

Import safety (SPEC §4)
-----------------------
``google.adk`` is heavy and GCP-only. All ADK imports are quarantined inside
:func:`build_root_agent`, and the module-level ``root_agent`` is built lazily via
:class:`_LazyRootAgent` so merely importing this module never requires ADK : the
on-prem/test profile imports it cleanly.

Deploying to Agent Runtime
--------------------------
Wrap and deploy with the Agent Platform SDK (region pinned to ``asia-southeast1``)::

    from vertexai import agent_engines
    from cio_advisory.agent.root_agent import build_root_agent
    from cio_advisory.config import Settings

    remote = agent_engines.create(
        build_root_agent(Settings.load()),
        requirements=["google-adk==2.3.0", "cio-advisory"],
    )  # -> reasoningEngine resource; record it in settings.agent_engine.resource_name
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents import LlmAgent

ROOT_AGENT_NAME = "cio_advisory_assistant"

_ROOT_INSTRUCTION = (
    "You are the B3 CIO Advisory Assistant for relationship managers (RMs) at a private "
    "bank. You connect the bank's CIO house views to a client's portfolio and produce "
    "personalised, suitability-checked talking points.\n\n"
    "CRITICAL: you produce decision-support, NOT financial advice. Never phrase output as "
    "a recommendation or directive to act; the RM is the human checker and signs off any "
    "advice given to the client.\n\n"
    "Routing:\n"
    "- 'Prepare a briefing for client X' -> call build_briefing.\n"
    "- 'What can I talk to client X about?' -> call generate_talking_points.\n"
    "- 'Is theme T suitable for client X?' -> call check_suitability.\n"
    "- Need recent public-web corroboration -> delegate to the web_grounding sub-agent; "
    "treat its results as secondary evidence only.\n\n"
    "Rules:\n"
    "- Every talking point must carry a citation to a CIO house view and a suitability "
    "verdict. Never invent a house view, a holding, a price, or a forecast.\n"
    "- Drop or flag any theme the suitability check marks REVIEW or UNSUITABLE; never "
    "present an unsuitable theme as a recommendation.\n"
    "- Do not request, repeat or store client personal data; it is redacted at the "
    "boundary and must not appear in your output."
)


def build_root_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the root ADK ``LlmAgent`` for the assistant.

    Wires the three FunctionTools, the optional ``google_search`` grounding sub-agent (as
    an ``AgentTool``), and the redact/guardrail/audit callbacks built from the DI
    container. The reasoning model runs at ``thinking=high`` (SPEC §3). All ADK imports are
    local to this function (SPEC §4).
    """
    settings = settings or Settings.load()

    from google.adk.agents import LlmAgent
    from google.adk.tools.agent_tool import AgentTool
    from google.genai import types

    from ..config import build_container
    from .callbacks import build_callbacks, configure_span_privacy
    from .grounding_agent import build_grounding_agent
    from .tools import build_function_tools

    # PII must never land in trace spans (SPEC §3); set before anything runs.
    configure_span_privacy()

    container = build_container(settings)
    callbacks = build_callbacks(container)

    tools: list[Any] = list(build_function_tools())

    grounding_agent = build_grounding_agent(settings)
    if grounding_agent is not None:
        tools.append(AgentTool(agent=grounding_agent))

    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )

    return LlmAgent(
        name=ROOT_AGENT_NAME,
        model=settings.models.reasoning,
        description=(
            "Suitability-checked CIO advisory assistant: advisory briefings, talking "
            "points and suitability checks for private-bank RMs. Decision-support, not advice."
        ),
        instruction=_ROOT_INSTRUCTION,
        tools=tools,
        generate_content_config=generate_content_config,
        before_model_callback=callbacks["before_model_callback"],
        after_model_callback=callbacks["after_model_callback"],
        after_agent_callback=callbacks["after_agent_callback"],
    )


def to_a2a_app(settings: Settings | None = None) -> Any:
    """Expose the root agent as an A2A app (serves ``/.well-known/agent-card.json``)."""
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    return to_a2a(build_root_agent(settings))


class _LazyRootAgent:
    """Lazy proxy so ``import root_agent`` never pulls in ADK.

    ADK discovers a module-level ``root_agent``. We must expose that name without forcing
    ADK to be importable at module import time (on-prem/test profile, SPEC §4). The real
    ``LlmAgent`` is built on first attribute access and cached.
    """

    __slots__ = ("_agent",)

    def __init__(self) -> None:
        self._agent: LlmAgent | None = None

    def _resolve(self) -> LlmAgent:
        if self._agent is None:
            self._agent = build_root_agent()
        return self._agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "unbuilt" if self._agent is None else "built"
        return f"<LazyRootAgent {ROOT_AGENT_NAME} ({state})>"


# ADK convention: a module-level ``root_agent`` the runtime discovers. Lazy so importing
# this module is safe without ADK installed (SPEC §4).
root_agent = _LazyRootAgent()
