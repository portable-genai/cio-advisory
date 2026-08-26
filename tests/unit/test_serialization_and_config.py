"""Unit tests for serialization, Settings.load, Container wiring, and the review policy.

* domain/serialization.to_jsonable round-trips enums (-> .value) and datetimes.
* Settings.load parses config/settings.yaml.
* Container under profile=onprem binds the on-prem placeholder adapters, and each bound
  adapter satisfies its runtime_checkable Protocol (structural parity).
* CioReviewPolicy : a briefing always requires review; REVIEW/UNSUITABLE points escalate.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pii_kit import DEFAULT_JURISDICTIONS
from tests.conftest import load_policy

from cio_advisory import ports
from cio_advisory.config import Container, LocalSettings, Settings, SuitabilitySettings
from cio_advisory.domain.models import (
    AdvisoryBriefing,
    AuditEvent,
    Citation,
    Decision,
    RiskAppetite,
    SourceType,
    Stance,
    SuitabilityAssessment,
    SuitabilityVerdict,
    TalkingPoint,
)

CONFIG_PATH = "config/settings.yaml"

PORT_PROTOCOLS = {
    "house_view": ports.HouseViewRetrievalPort,
    "portfolio": ports.PortfolioPort,
    "llm": ports.LLMPort,
    "grounding": ports.GroundingPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "agent_runtime": ports.AgentRuntimePort,
    "session": ports.SessionPort,
    "memory": ports.MemoryPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
    "identity": ports.IdentityPort,
}


# --------------------------------------------------------------------------- #
# to_jsonable
# --------------------------------------------------------------------------- #
def _to_jsonable():
    from cio_advisory.domain.serialization import to_jsonable

    return to_jsonable


def test_to_jsonable_enum_becomes_value():
    to_jsonable = _to_jsonable()
    assert to_jsonable(RiskAppetite.BALANCED) == "balanced"
    assert to_jsonable(Stance.OVERWEIGHT) == "overweight"
    assert to_jsonable(SuitabilityVerdict.UNSUITABLE) == "unsuitable"
    assert to_jsonable(Decision.BLOCKED) == "blocked"


def test_to_jsonable_datetime_is_json_safe_string():
    to_jsonable = _to_jsonable()
    dt = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    out = to_jsonable(dt)
    assert isinstance(out, str)
    assert json.loads(json.dumps(out)) == out
    assert "2026-06-20" in out


def test_to_jsonable_briefing_roundtrips_through_json():
    to_jsonable = _to_jsonable()
    assessment = SuitabilityAssessment(
        theme="AI infrastructure build-out",
        verdict=SuitabilityVerdict.REVIEW,
        citations=(
            Citation(
                source_id="cio-2026q2-ai-infrastructure",
                source_type=SourceType.HOUSE_VIEW,
                title="AI infrastructure build-out",
            ),
        ),
    )
    point = TalkingPoint(
        headline="A point to discuss",
        body="body",
        house_view_theme="AI infrastructure build-out",
        linked_holdings=("equity",),
        suitability=assessment,
        citations=assessment.citations,
        is_advice=False,
    )
    briefing = AdvisoryBriefing(client_id="client-000042", talking_points=(point,))
    out = to_jsonable(briefing)
    text = json.dumps(out)  # must not raise
    reloaded = json.loads(text)
    assert reloaded["requires_human_review"] is True
    assert reloaded["talking_points"][0]["is_advice"] is False
    assert reloaded["talking_points"][0]["suitability"]["verdict"] == "review"
    assert reloaded["not_advice_disclaimer"]


def test_to_jsonable_audit_event_is_worm_serialisable():
    to_jsonable = _to_jsonable()
    event = AuditEvent(
        action="briefing",
        actor="rm",
        decision=Decision.ALLOWED,
        redacted_prompt="client-000042",
        redacted_response="ok",
    )
    out = to_jsonable(event)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["decision"] == "allowed"
    assert reloaded["action"] == "briefing"
    assert reloaded["resource"] == "cio-advisory"


# --------------------------------------------------------------------------- #
# Settings.load
# --------------------------------------------------------------------------- #
def test_settings_load_parses_yaml():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "asia-southeast1"
    assert settings.models.reasoning == "gemini-3.7-flash"
    assert settings.models.triage == "gemini-3.1-flash-lite"
    assert settings.suitability.concentration_limit == 0.40
    assert settings.suitability.aggressive_asset_classes == (
        "equity",
        "alternatives",
        "real_assets",
    )
    assert set(PORT_PROTOCOLS) <= set(settings.adapters)


def test_settings_yaml_pii_kit_matches_the_shipped_default():
    """The YAML default and the pack's own default must not drift apart.

    ``config/settings.yaml`` restates the jurisdiction list for discoverability, so pin it to
    the shipped default (the shared ``pii-kit`` APAC reference set): the redactor, the DLP
    custom info types and the eval gate's leak check all key off that pack, and a settings file
    that quietly disagreed would change what is masked without changing what the gate checks.
    """
    settings = Settings.load(CONFIG_PATH)
    assert settings.pii.jurisdictions == DEFAULT_JURISDICTIONS


def test_pii_jurisdictions_env_override(monkeypatch):
    monkeypatch.setenv("CIO_PII_JURISDICTIONS", "jp, au ")
    settings = Settings.load(CONFIG_PATH)
    # Upper-cased, whitespace-stripped, and a tuple regardless of where the value came from.
    assert settings.pii.jurisdictions == ("JP", "AU")


def test_settings_pins_models_to_allowed_ids():
    settings = Settings.load(CONFIG_PATH)
    assert settings.models.reasoning != "gemini-2.0-flash"
    assert settings.models.triage != "gemini-2.0-flash"
    assert settings.models.reasoning.startswith("gemini-3")


def test_composition_root_threads_suitability_override(monkeypatch):
    from cio_advisory.api.deps import build_advisory_service

    monkeypatch.setenv("CIO_PROFILE", "local")
    settings = replace(
        Settings.load(CONFIG_PATH),
        profile="local",
        profile_explicit=True,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        suitability=SuitabilitySettings(concentration_limit=0.17),
    )
    service = build_advisory_service(Container(settings))
    assert service._suitability.concentration_limit == 0.17


# --------------------------------------------------------------------------- #
# Container binds on-prem adapters under profile=onprem, with structural parity.
# --------------------------------------------------------------------------- #
def _onprem_settings() -> Settings:
    s = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=s.project_id,
        region=s.region,
        profile="onprem",
        kms_key=s.kms_key,
        grounding_enabled=s.grounding_enabled,
        models=s.models,
        house_views=s.house_views,
        bigquery=s.bigquery,
        model_armor=s.model_armor,
        dlp=s.dlp,
        logging=s.logging,
        agent_engine=s.agent_engine,
        suitability=s.suitability,
        adapters=s.adapters,
    )


def test_container_binds_onprem_adapters_with_protocol_parity():
    container = Container(_onprem_settings())
    for port_name, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port_name)
        assert isinstance(adapter, protocol), (
            f"on-prem adapter for '{port_name}' is not structurally a {protocol.__name__}"
        )


def test_container_refuses_a_missing_profile_binding():
    settings = _onprem_settings()
    adapters = {name: dict(binding) for name, binding in settings.adapters.items()}
    adapters["guardrail"].pop("onprem")
    incomplete = Settings(
        project_id=settings.project_id,
        region=settings.region,
        profile="onprem",
        kms_key=settings.kms_key,
        grounding_enabled=settings.grounding_enabled,
        models=settings.models,
        house_views=settings.house_views,
        bigquery=settings.bigquery,
        model_armor=settings.model_armor,
        dlp=settings.dlp,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        suitability=settings.suitability,
        adapters=adapters,
    )
    with pytest.raises(KeyError, match="under profile 'onprem'"):
        _ = Container(incomplete).guardrail


# --------------------------------------------------------------------------- #
# CioReviewPolicy
# --------------------------------------------------------------------------- #
def _point(verdict: SuitabilityVerdict | None) -> TalkingPoint:
    suitability = None if verdict is None else SuitabilityAssessment(theme="t", verdict=verdict)
    return TalkingPoint(headline="h", body="b", house_view_theme="t", suitability=suitability)


def test_review_policy_always_requires_review():
    policy = load_policy("CioReviewPolicy")()
    assert policy.requires_review((_point(SuitabilityVerdict.SUITABLE),)) is True
    assert policy.requires_review(()) is True


def test_review_policy_escalates_on_review_or_unsuitable():
    policy = load_policy("CioReviewPolicy")()
    assert policy.escalates((_point(SuitabilityVerdict.SUITABLE),)) is False
    assert policy.escalates((_point(SuitabilityVerdict.REVIEW),)) is True
    assert policy.escalates((_point(SuitabilityVerdict.UNSUITABLE),)) is True


def test_agent_service_uses_configured_suitability_policy():
    """The ADK surface must share the API's adopter-owned suitability composition root."""
    from dataclasses import replace

    from cio_advisory.agent.tools import _service
    from cio_advisory.domain.models import AssetClass

    settings = replace(
        Settings.load(CONFIG_PATH),
        suitability=SuitabilitySettings(
            concentration_limit=0.17,
            aggressive_asset_classes=("fixed_income",),
            complex_asset_classes=("cash",),
        ),
    )
    service = _service(settings)
    assert service._suitability.concentration_limit == 0.17
    assert service._suitability.aggressive_asset_classes == frozenset({AssetClass.FIXED_INCOME})
    assert service._suitability.complex_asset_classes == frozenset({AssetClass.CASH})


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_suitability_limit_refuses_out_of_range_values(value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        SuitabilitySettings(concentration_limit=value)


def test_suitability_asset_class_typo_refuses_at_configuration() -> None:
    with pytest.raises(ValueError, match="unknown asset classes"):
        SuitabilitySettings(aggressive_asset_classes=("equites",))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
