"""Contract tests: the ``onprem`` and ``local`` adapters are structural parity of the ports.

For every port the catalog declares, this iterates the adapter map and, for both the
``onprem`` and ``local`` profiles, imports + constructs the bound class (which must build
cleanly with **no Google Cloud SDK** installed), then asserts:

  1. the constructed instance satisfies its runtime_checkable Protocol (isinstance), and
  2. every method/property the Protocol declares actually exists on the instance.

It additionally proves the two profiles' distinct contracts:

* ``onprem`` is the fail-fast Google Distributed Cloud migration target: every method
  raises ``NotImplementedError`` (proven on a representative port), and
* ``local`` is a WORKING offline stack: the same ports construct and answer in-process.

This is the proof of the ports-and-adapters / no-lock-in promise (P-02): the on-prem
migration target and the offline local stack implement the exact same interface as the
managed GCP stack.
"""

from __future__ import annotations

from typing import Protocol, get_type_hints

import pytest

from cio_advisory import config, ports
from cio_advisory.config import LocalSettings, Settings, instantiate

CONFIG_PATH = "config/settings.yaml"

# Every port name in settings.adapters mapped to its Protocol.
PORT_PROTOCOLS: dict[str, type] = {
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
    "review_router": ports.ReviewRouterPort,
}

# Profiles whose adapters must construct + satisfy the Protocols with no GCP SDK.
# ``live`` constructs SDK-free too (lazy google imports in the grounded research
# adapters); an unbound live port would silently fall back to a managed GCP adapter.
SDK_FREE_PROFILES = ("onprem", "local", "live")


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    # Point the local stores at in-memory SQLite so the contract test stays ephemeral.
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile=profile,
        kms_key=base.kms_key,
        grounding_enabled=base.grounding_enabled,
        models=base.models,
        house_views=base.house_views,
        bigquery=base.bigquery,
        model_armor=base.model_armor,
        dlp=base.dlp,
        logging=base.logging,
        agent_engine=base.agent_engine,
        suitability=base.suitability,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:
        # Fallback for older typing internals: union of annotations + callables.
        members |= set(get_type_hints(protocol).keys())
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            members.add(name)
    return {m for m in members if not m.startswith("_")}


def test_port_protocols_matches_settings_adapters():
    """The hand-maintained PORT_PROTOCOLS map must EQUAL the ports bound in settings.

    ``test_every_port_has_onprem_and_local_bindings`` only walks PORT_PROTOCOLS ->
    settings (one direction), so a fork that binds a NEW port in config/settings.yaml but
    forgets its PORT_PROTOCOLS entry gets ZERO parity / constructor / onprem-binding
    enforcement with a green CI (silent drift). This set-equality closes both directions:
    it fails if a port is bound in ``settings.adapters`` but absent from PORT_PROTOCOLS
    (so untested), AND if a port is in PORT_PROTOCOLS with no ``settings.adapters`` binding.
    """
    settings = Settings.load(CONFIG_PATH)
    bound = set(settings.adapters)
    declared = set(PORT_PROTOCOLS)
    missing_from_map = bound - declared
    missing_from_settings = declared - bound
    assert not missing_from_map, (
        f"ports bound in settings.adapters but absent from PORT_PROTOCOLS "
        f"(so untested): {sorted(missing_from_map)}. Add them to the parity map."
    )
    assert not missing_from_settings, (
        f"ports in PORT_PROTOCOLS with no settings.adapters binding: "
        f"{sorted(missing_from_settings)}."
    )


def test_every_port_has_an_explicit_binding_for_every_profile():
    settings = Settings.load(CONFIG_PATH)
    for port_name in PORT_PROTOCOLS:
        binding = settings.adapters.get(port_name, {})
        missing = set(config.RUNTIME_PROFILES) - set(binding)
        assert not missing, f"port '{port_name}' has no explicit bindings for {sorted(missing)}"


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_satisfies_protocol(profile: str, port_name: str):
    settings = _settings(profile)
    protocol = PORT_PROTOCOLS[port_name]
    dotted = settings.adapters[port_name][profile]

    # Import + construct with only Settings (the adapter convention), no GCP SDK.
    adapter = instantiate(dotted, settings)

    # 1. Structural conformance via runtime_checkable Protocol.
    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    # 2. Every declared Protocol member exists. Check on the *class* (via the MRO), not
    #    the instance: a placeholder property getter may raise, so ``hasattr`` would
    #    wrongly report it missing. Looking the name up on the type tests for declaration
    #    without invoking the getter.
    members = _protocol_members(protocol)
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in members:
        assert member in declared, (
            f"{dotted} is missing port method/attr '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_constructs_with_single_settings_arg(profile: str, port_name: str):
    """The build contract: every adapter is ``Adapter(settings: Settings)``."""
    settings = _settings(profile)
    dotted = settings.adapters[port_name][profile]
    module_path, _, class_name = dotted.partition(":")
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    # Must accept exactly one positional Settings argument and build cleanly.
    instance = cls(settings)
    assert instance is not None


def test_onprem_house_view_fails_fast():
    """The on-prem stubs are fail-fast: a representative port raises NotImplementedError."""
    settings = _settings("onprem")
    adapter = instantiate(settings.adapters["house_view"]["onprem"], settings)
    with pytest.raises(NotImplementedError):
        adapter.retrieve("anything")


def test_local_house_view_returns_real_views():
    """The local stack is WORKING: house-view retrieval returns real, cited views offline."""
    settings = _settings("local")
    adapter = instantiate(settings.adapters["house_view"]["local"], settings)
    views = adapter.retrieve("AI infrastructure equity", top_k=5)
    assert views, "local FTS5 retrieval returned nothing for the seeded corpus"
    assert all(v.citation is not None for v in views), "house-view citation required"


def test_shared_types_are_the_commons_objects_not_copies():
    """The shared ports and value types must BE the commons objects, not look-alikes.

    Every structural check in this file passes for a hand-copied Protocol: ``isinstance``
    against a ``runtime_checkable`` Protocol compares method names, and a copy has the same
    method names by construction. That is exactly how sixteen repositories each grew their own
    ``ObservabilityTracerPort`` / ``TokenUsage`` / ``EvalReport`` and drifted apart while every
    suite stayed green : one repo dropped the evaluation port, two dropped its ``gate`` method,
    and the copies of ``EvalReport`` disagreed on which evidence fields even existed.

    ``is`` is the only assertion that can see the difference. It fails the moment somebody
    redeclares one of these locally, which is the drift this test exists to make impossible.
    """
    import agent_eval_kit
    import hex_service_kit.observability as hsk_obs

    from cio_advisory.domain import models

    assert ports.ObservabilityTracerPort is hsk_obs.ObservabilityTracerPort
    assert ports.TokenUsage is hsk_obs.TokenUsage
    assert ports.EvaluationGatePort is agent_eval_kit.EvaluationGatePort
    assert models.TokenUsage is hsk_obs.TokenUsage
    assert models.EvalReport is agent_eval_kit.EvalReport
    assert models.EvalMetricResult is agent_eval_kit.EvalMetricResult


def test_all_protocols_are_runtime_checkable():
    for protocol in PORT_PROTOCOLS.values():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} must be @runtime_checkable"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
