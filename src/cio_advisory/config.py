"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` : proof of the
ports-and-adapters / no-lock-in principle (P-02). Every adapter follows one construction
convention: ``Adapter(settings: Settings)``.
"""

from __future__ import annotations

import functools
import importlib
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from .envread import (
    ConfiguredEmptyError,
    EnvSetting,
    boolean_setting,
    optional_setting,
    read_env_setting,
    setting_or_default,
)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

#: The one environment variable that selects the runtime profile. Only :func:`resolve_profile`
#: may read it; ``tests/unit/test_profile_single_source.py`` fails the build if another module
#: re-derives the profile with its own permissive default.
_PROFILE_ENV = "CIO_PROFILE"

#: Every profile the adapter table binds. An exact, case-sensitive membership test, so a
#: mis-capitalised value is a boot failure rather than a profile that matches no posture.
RUNTIME_PROFILES = frozenset({"local", "live", "gcp", "platform", "onprem"})

#: The profile string handed to every INTERNET-FACING relaxation when ``CIO_PROFILE`` was
#: never set. Deliberately NOT a member of :data:`RUNTIME_PROFILES` and it never reaches an
#: adapter binding: it exists so that "no choice was made" is a distinct input to the
#: security layers rather than being indistinguishable from a deliberately chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of ``CIO_PROFILE``, and what each consumer must key off.

    The two derived strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent a choice this is still ``local``, because the
    #: alternative is importing cloud SDKs that are not installed; what an unconsented run
    #: loses is the identity relaxation, not the SDK-free data adapters.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (``CIO_PROFILE`` set, or ``profile:`` written into
    #: the settings file)? Direct construction is deliberate by definition, so the default is
    #: True and only :meth:`Settings.load` can produce False.
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off: the CORS allowlist, the dev personas.

        These grant something extra to ``local``, so an unconsented run must NOT look like
        ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's allowlist and
        no persona's profile.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay confined.
        """
        return self.profile if self.explicit else "local"


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose. Without it ``CIO_PROFILE=Local``
    matched no entry in the adapter table. The container also requires an exact binding, so
    neither a typo nor an incomplete profile can silently select managed cloud adapters.
    """
    if profile not in RUNTIME_PROFILES:
        allowed = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {allowed}")
    return profile


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(
    environ: Mapping[str, str] | None = None, *, file_profile: str = ""
) -> ProfileChoice:
    """Read ``CIO_PROFILE`` once: absent is NO CHOICE and configured-empty refuses.

    Resolution is three-state: unset is carried as unconsented; configured-empty refuses;
    set-and-valid is carried through; set-and-invalid raises here rather than at the first
    request, so a typo is a boot failure. ``file_profile`` is the settings file's own
    ``profile:`` key, which counts as a deliberate choice when it names a profile; the
    shipped file leaves it as ``${CIO_PROFILE}`` so an unset variable stays unset instead of
    materialising there as a written-down ``local``.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value; unset it for the unconsented "
            "loopback-only posture, or name a supported profile."
        )
    if setting.has_value:
        return ProfileChoice(profile=_validate_profile(setting.value), explicit=True)
    chosen = file_profile.strip()
    if chosen:
        return ProfileChoice(profile=_validate_profile(chosen), explicit=True)
    return ProfileChoice(profile="local", explicit=False)


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` tokens in strings recursively."""
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return setting_or_default(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


#: The profiles whose runtime is a managed cloud, for :attr:`Settings.runtime`. ``live`` is
#: NOT one: its models are the Gemini API but the process itself runs on the operator's
#: laptop, and the banner states WHERE, not WHOSE model. ``onprem`` is not one either.
_MANAGED_PROFILES: frozenset[str] = frozenset({"gcp", "platform"})


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.5-flash"
    triage: str = "gemini-3.5-flash"
    hard_reasoning: str = "gemini-3.5-flash"  # Preview : feature-flagged off by default
    use_hard_reasoning: bool = False


#: The locations Agent Search (Discovery Engine) serves, and the only values a house-view store
#: location may take. No Cloud region is among them: a store at ``asia-southeast1`` cannot be
#: created, and a client pointed at one addresses a host that does not exist.
#: ``infra/terraform/variables.tf`` validates ``house_views_location`` against the same three,
#: and ``tests/contract/test_house_view_store_location.py`` fails when the two lists differ.
AGENT_SEARCH_LOCATIONS: tuple[str, ...] = ("global", "us", "eu")


def agent_search_location(location: str) -> str:
    """Return ``location`` when Agent Search serves it; refuse anything else before any call."""
    if location not in AGENT_SEARCH_LOCATIONS:
        allowed = ", ".join(AGENT_SEARCH_LOCATIONS)
        raise ValueError(
            f"house-view store location {location!r} is not an Agent Search location; "
            f"expected one of: {allowed}. A Cloud region is never one."
        )
    return location


@dataclass(frozen=True)
class HouseViewSettings:
    # The governed enterprise-knowledge-base is the platform retrieval backend; these settings
    # describe the Agent Search store the standalone gcp profile searches and
    # scripts/ingest_house_views.py fills. ``location`` is read from CIO_HOUSE_VIEWS_LOCATION
    # (config/settings.yaml) and must equal the Terraform stack's house_views_location: the two
    # halves disagreeing about where the store lives is a 404 at the first briefing, never a
    # plan error.
    data_store_id: str = "cio-house-views"
    location: str = "us"
    serving_config: str = "default_search"
    engine_id: str = "cio-advisory-engine"

    def __post_init__(self) -> None:
        agent_search_location(self.location)


@dataclass(frozen=True)
class BigQuerySettings:
    # Portfolio + KYC profile store. Internal customer data, CMEK, in-region.
    dataset: str = "wealth_portfolio"
    portfolio_table: str = "holdings"
    profile_table: str = "client_profiles"
    instruments_table: str = "instruments"
    model_portfolio_table: str = "model_portfolios"
    manifest_table: str = "book_manifest"
    location: str = "asia-southeast1"


#: The environment variables that switch each cheap runtime control, read in three states:
#: unset is ON (the reference posture keeps cheap controls on), a boolean value wins, and an
#: emptied or unrecognised value refuses at boot. See the fleet's runtime-control contract.
GUARDRAIL_ENV = "CIO_GUARDRAIL"
PII_REDACTION_ENV = "CIO_PII_REDACTION"
REVIEW_ROUTING_ENV = "CIO_REVIEW_ROUTING"
#: The human-review-console base URL the review router submits to. Required at boot under a
#: managed profile while review routing is on, so a missing console is a named refusal rather
#: than a hand-off that fails, silently, on every briefing.
HUMAN_REVIEW_URL_ENV = "HUMAN_REVIEW_URL"
#: The bearer audience the portal's IAP edge accepts for the console hand-off: the IAP OAuth
#: client id. Under ``gcp`` the console is an embedded app behind that edge, so
#: ``HUMAN_REVIEW_URL`` is its edge path (``https://<edge-host>/apps/human-review-console/api``)
#: and the router mints a fresh ID token for this audience per submission. Read in three states:
#: unset keeps the static ``S2S_TOKEN`` bearer, emptied refuses, a value is minted for.
HUMAN_REVIEW_IAP_AUDIENCE_ENV = "HUMAN_REVIEW_IAP_AUDIENCE"
#: The managed profile whose console is reached through the portal's IAP edge, and so the one
#: profile under which review routing needs the audience as well as the URL.
IAP_EDGE_PROFILE = "gcp"

#: The guardrail class that calls a Model Armor template, and so needs one named at boot.
_MODEL_ARMOR_GUARDRAIL = "ModelArmorGuardrailAdapter"

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ControlSwitches:
    """Which cheap runtime controls this process runs. Every one defaults on."""

    guardrail: bool = True
    pii_redaction: bool = True
    review_routing: bool = True

    @classmethod
    def from_env(cls) -> ControlSwitches:
        return cls(
            guardrail=boolean_setting(GUARDRAIL_ENV, default=True),
            pii_redaction=boolean_setting(PII_REDACTION_ENV, default=True),
            review_routing=boolean_setting(REVIEW_ROUTING_ENV, default=True),
        )

    def switched_off(self) -> tuple[str, ...]:
        """The environment variables of every control that is off, for the startup warning."""
        states = (
            (GUARDRAIL_ENV, self.guardrail),
            (PII_REDACTION_ENV, self.pii_redaction),
            (REVIEW_ROUTING_ENV, self.review_routing),
        )
        return tuple(name for name, on in states if not on)


@dataclass(frozen=True)
class ModelArmorSettings:
    template_id: str = "cio-advisory-guardrail"
    host: str = "modelarmor.asia-southeast1.rep.googleapis.com"


@dataclass(frozen=True)
class DlpSettings:
    inspect_template: str = ""  # projects/.../inspectTemplates/...
    deidentify_template: str = ""  # projects/.../deidentifyTemplates/...


@dataclass(frozen=True)
class PiiSettings:
    """Which jurisdictions' national identifiers the redactor and the eval gate detect.

    Drives BOTH the local regex redactor and the GCP DLP custom info types from one pattern
    source (the shared ``pii-kit`` package), so a deployment outside APAC detects its own
    identifiers by editing this list rather than changing code. The supported packs live in
    ``pii_kit.patterns`` (``pii_kit.DEFAULT_JURISDICTIONS`` is its APAC reference default,
    which this mirrors); override at runtime with ``CIO_PII_JURISDICTIONS`` (comma-separated
    ISO-3166 alpha-2 codes). Unknown codes degrade safely to universal email/phone only.
    """

    jurisdictions: tuple[str, ...] = ("SG", "HK", "JP", "AU")


def _pii_settings(raw: Any) -> PiiSettings:
    """Build :class:`PiiSettings`, honouring the env override and normalising the codes.

    ``CIO_PII_JURISDICTIONS`` (comma-separated) wins over the settings file so an operator
    can retarget the pack without editing YAML. Codes are upper-cased and coerced to a
    tuple: YAML yields a list, the env yields a string, and the frozen dataclass is compared
    by value, so the type must not depend on where the value came from.
    """
    data = dict(raw or {})
    env = optional_setting("CIO_PII_JURISDICTIONS")
    if env is not None:
        # Three-state: unset means "no override" and the settings file (or the default pack)
        # stands. Set to a value that names no jurisdiction is not a request for fewer
        # detectors, it is a broken override, and honouring it would leave the redactor and
        # the eval gate running with the national-identifier patterns switched off while
        # reporting clean. Only a value naming at least one jurisdiction narrows the set.
        if not [code for code in env.split(",") if code.strip()]:
            raise ValueError(
                "CIO_PII_JURISDICTIONS is set but names no jurisdiction; refusing to redact "
                "with an empty detector set. Unset it to keep the configured pack, or name "
                "the ISO-3166 alpha-2 codes to detect."
            )
        data["jurisdictions"] = env.split(",")
    codes = data.get("jurisdictions")
    if codes is not None:
        if isinstance(codes, str):
            codes = codes.split(",")
        data["jurisdictions"] = tuple(str(c).strip().upper() for c in codes if str(c).strip())
    return PiiSettings(**data)


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "cio-advisory-audit"
    bucket: str = "cio-advisory-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "cio-advisory"


@dataclass(frozen=True)
class SuitabilitySettings:
    # The concentration limit the SuitabilityPolicy uses (single-asset-class weight).
    concentration_limit: float = 0.40
    aggressive_asset_classes: tuple[str, ...] = ("equity", "alternatives", "real_assets")
    complex_asset_classes: tuple[str, ...] = ("alternatives", "real_assets")

    def __post_init__(self) -> None:
        from .domain.models import AssetClass

        if not 0.0 <= self.concentration_limit <= 1.0:
            raise ValueError("suitability.concentration_limit must be between 0 and 1")
        allowed = {item.value for item in AssetClass}
        for name, values in (
            ("aggressive_asset_classes", self.aggressive_asset_classes),
            ("complex_asset_classes", self.complex_asset_classes),
        ):
            unknown = sorted(set(values) - allowed)
            if unknown:
                raise ValueError(f"suitability.{name} contains unknown asset classes: {unknown}")


def _suitability_settings(raw: dict[str, Any]) -> SuitabilitySettings:
    for key in ("aggressive_asset_classes", "complex_asset_classes"):
        if key in raw:
            raw[key] = tuple(str(value).strip().lower() for value in raw[key] if str(value).strip())
    if "concentration_limit" in raw:
        raw["concentration_limit"] = float(raw["concentration_limit"])
    return SuitabilitySettings(**raw)


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + append-only audit).

    Empty strings select the per-package default under ``~/.cio_advisory/``; tests pass
    ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here.
    """

    db_path: str = ""  # SQLite FTS5 house-view index; "" => ~/.cio_advisory/local.db
    audit_path: str = ""  # append-only audit store;     "" => ~/.cio_advisory/audit.db
    book_path: str = ""  # DuckDB client book;           "" => ~/.cio_advisory/book.duckdb


@dataclass(frozen=True)
class LiveSettings:
    """The ``live`` profile: real grounded market research, generated by the Gemini API.

    The profile carries no model-server settings. House-view themes come from Gemini
    google_search grounded research over real published market commentary, so the system
    already cannot answer without leaving the data centre; generating the narrative on a
    laptop model beside that would be a local-model claim the use case cannot support
    (org decision, 2026-08-30). Requires GOOGLE_CLOUD_PROJECT + ADC. Research is cached
    on disk so a demo re-run does not re-research the same day.
    """

    max_output_tokens: int = 2048
    research_cache_path: str = ""  # "" => ~/.cio_advisory/live-house-views.json
    research_cache_ttl_seconds: int = 6 * 3600  # 0 disables the cache


def _live_settings(raw: dict[str, Any]) -> LiveSettings:
    """Build LiveSettings with numeric coercion (env interpolation yields strings)."""
    for key, cast in (
        ("max_output_tokens", int),
        ("research_cache_ttl_seconds", int),
    ):
        if key in raw:
            raw[key] = cast(raw[key])
    return LiveSettings(**raw)


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = "asia-southeast1"
    # gcp | local | live | platform | onprem; local is the SDK-free adapter family and prod
    # deploys set CIO_PROFILE=gcp explicitly.
    profile: str = "local"
    # Was the profile CHOSEN, or merely inherited because nothing named one? ``load`` sets
    # this False when neither ``CIO_PROFILE`` nor the settings file's ``profile:`` key names
    # a profile. Direct construction is deliberate by definition (a caller named it in code),
    # so the default is True. See :attr:`exposure_profile` for what it gates.
    profile_explicit: bool = True
    kms_key: str = ""  # projects/.../cryptoKeys/... (regional)
    grounding_enabled: bool = False
    models: ModelSettings = field(default_factory=ModelSettings)
    house_views: HouseViewSettings = field(default_factory=HouseViewSettings)
    bigquery: BigQuerySettings = field(default_factory=BigQuerySettings)
    model_armor: ModelArmorSettings = field(default_factory=ModelArmorSettings)
    dlp: DlpSettings = field(default_factory=DlpSettings)
    pii: PiiSettings = field(default_factory=PiiSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    suitability: SuitabilitySettings = field(default_factory=SuitabilitySettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    live: LiveSettings = field(default_factory=LiveSettings)
    #: Which cheap runtime controls run; see :class:`ControlSwitches`.
    controls: ControlSwitches = field(default_factory=ControlSwitches)
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def runtime(self) -> str:
        """Where this process is running, as the UI banner states it: ``gcp`` or ``local``.

        Derived from the profile, never sniffed from the environment. A console that read
        its runtime from ``window.location`` would be right until the deployment served
        through a proxy and wrong silently after that, so the service is the one asked.
        ``onprem`` reads ``local`` deliberately: it runs on the adopter's own iron, and
        "on GCP" is the one sentence that deployment must never print.
        """
        return "gcp" if self.profile in _MANAGED_PROFILES else "local"

    @property
    def generator_model(self) -> str:
        """Which model answers, for the UI banner (org decision, 2026-08-30).

        Read off the LLM binding the container will actually build, not from a second
        field someone has to remember to update. A repo that rebinds ``llm`` for a profile
        changes what the banner says in the same edit, which is the only way the two stay
        true to each other: the previous shape of this value in the fleet was a settings
        string, and a settings string is a claim about the binding rather than the binding.
        """
        binding = self.adapters.get("llm", {}).get(self.profile, "")
        _, _, class_name = binding.partition(":")
        if class_name == "GeminiLLMAdapter":
            models = self.models
            return models.hard_reasoning if models.use_hard_reasoning else models.reasoning
        if class_name == "OnPremLLMAdapter":
            # The on-prem adapter is a fail-fast migration placeholder: it raises rather
            # than generating. Naming a model here would advertise one that never answers.
            return "onprem-not-implemented"
        return "deterministic-offline-stub"

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off, never the raw :attr:`profile`."""
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit).exposure_profile

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off; ``local`` is the RESTRICTIVE case there."""
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit).bind_profile

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        path = Path(path or setting_or_default("CIO_SETTINGS", "config/settings.yaml"))
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        nested: dict[str, Any] = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "house_views": HouseViewSettings(**(raw.pop("house_views", {}) or {})),
            "bigquery": BigQuerySettings(**(raw.pop("bigquery", {}) or {})),
            "model_armor": ModelArmorSettings(**(raw.pop("model_armor", {}) or {})),
            "dlp": DlpSettings(**(raw.pop("dlp", {}) or {})),
            "pii": _pii_settings(raw.pop("pii", {})),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "suitability": _suitability_settings(raw.pop("suitability", {}) or {}),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
            "live": _live_settings(raw.pop("live", {}) or {}),
        }
        choice = resolve_profile(file_profile=str(raw.pop("profile", "") or ""))
        known = {f for f in Settings.__dataclass_fields__ if f not in nested}
        flat: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        flat.pop("profile_explicit", None)  # never settable from the settings file
        flat.pop("controls", None)  # switched by environment only, never the settings file
        settings = Settings(
            profile=choice.profile,
            profile_explicit=choice.explicit,
            controls=ControlSwitches.from_env(),
            **flat,
            **nested,
        )
        _refuse_unconfigured_controls(settings)
        return settings


def _refuse_unconfigured_controls(settings: Settings) -> None:
    """A control that is on under a managed profile must be able to work, checked at boot.

    Review routing on with no console named used to fail every hand-off inside the router,
    where the service swallowed it: the briefing reported "requires human review" and nothing
    reached the console. A Model Armor guardrail on with no template would build a malformed
    template path at the first request. Both are configuration errors, so both refuse here and
    say how to either configure the control or switch it off out loud.
    """
    if settings.profile not in _MANAGED_PROFILES:
        return
    controls = settings.controls
    if controls.review_routing and settings.profile == IAP_EDGE_PROFILE:
        _refuse_routing_without_the_edge(settings.profile)
    elif controls.review_routing and optional_setting(HUMAN_REVIEW_URL_ENV) is None:
        raise ConfiguredEmptyError(
            f"Review routing is on under profile {settings.profile!r} but {HUMAN_REVIEW_URL_ENV} "
            f"is not set. Name the human-review-console base URL, or set "
            f"{REVIEW_ROUTING_ENV}=off to run without routing."
        )
    guardrail = settings.adapters.get("guardrail", {}).get(settings.profile, "")
    if (
        controls.guardrail
        and guardrail.endswith(f":{_MODEL_ARMOR_GUARDRAIL}")
        and not settings.model_armor.template_id.strip()
    ):
        raise ConfiguredEmptyError(
            f"The guardrail is on under profile {settings.profile!r} but no Model Armor "
            f"template is configured. Name one, or set {GUARDRAIL_ENV}=off."
        )


def _refuse_routing_without_the_edge(profile: str) -> None:
    """Under the IAP-fronted profile, routing needs the console's edge path AND the audience.

    The console is reached through the portal's IAP edge, which accepts only an ID token minted
    for the IAP OAuth client id. A URL with no audience would send the static bearer the edge
    refuses, and an audience with no URL names nowhere to send it, so both are required and the
    refusal names both, whichever is missing.
    """
    url = optional_setting(HUMAN_REVIEW_URL_ENV)
    audience = optional_setting(HUMAN_REVIEW_IAP_AUDIENCE_ENV)
    missing = [
        name
        for name, value in ((HUMAN_REVIEW_URL_ENV, url), (HUMAN_REVIEW_IAP_AUDIENCE_ENV, audience))
        if value is None
    ]
    if missing:
        raise ConfiguredEmptyError(
            f"Review routing is on under profile {profile!r}, which reaches the "
            f"human-review-console through the portal's IAP edge, so it needs both "
            f"{HUMAN_REVIEW_URL_ENV} (the console's edge path) and "
            f"{HUMAN_REVIEW_IAP_AUDIENCE_ENV} (the IAP OAuth client id); not set: "
            f"{', '.join(missing)}. Name both, or set {REVIEW_ROUTING_ENV}=off to run without "
            "routing."
        )
    iap_audience_or_refuse(HUMAN_REVIEW_IAP_AUDIENCE_ENV, audience or "")


def iap_audience_or_refuse(name: str, value: str) -> str:
    """Refuse the one wrong IAP bearer audience an operator is most likely to paste.

    IAP compares its OWN assertion against the backend-service path
    (``/projects/<n>/global/backendServices/<id>``), and that path is NOT a bearer audience: a
    token minted for it is refused at the edge, and this process only ever sees the refusal,
    never the reason. The two values live side by side in a deployment record, so catching the
    mix-up here is the difference between a named configuration error and an unexplained 401.
    """
    if value.startswith("/projects/") or "/backendServices/" in value:
        raise ValueError(
            f"{name} must be the IAP OAuth client id, not the backend-service path "
            f"{value!r}: IAP compares that path against its own assertion and refuses it as a "
            "bearer audience."
        )
    return value


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the
    on-prem profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def house_view(self) -> Any:
        return self._bind("house_view")

    @cached_property
    def portfolio(self) -> Any:
        return self._bind("portfolio")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def grounding(self) -> Any:
        return self._bind("grounding")

    @cached_property
    def guardrail(self) -> Any:
        if not self.settings.controls.guardrail:
            from .adapters.controls import DisabledGuardrail

            return DisabledGuardrail(self.settings)
        return self._bind("guardrail")

    @cached_property
    def redaction(self) -> Any:
        if not self.settings.controls.pii_redaction:
            from .adapters.controls import DisabledRedaction

            return DisabledRedaction(self.settings)
        return self._bind("redaction")

    @cached_property
    def agent_runtime(self) -> Any:
        return self._bind("agent_runtime")

    @cached_property
    def session(self) -> Any:
        return self._bind("session")

    @cached_property
    def memory(self) -> Any:
        return self._bind("memory")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def registry(self) -> Any:
        return self._bind("registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")

    @cached_property
    def review_router(self) -> Any:
        if not self.settings.controls.review_routing:
            from .adapters.controls import DisabledReviewRouter

            return DisabledReviewRouter(self.settings)
        return self._bind("review_router")


@functools.cache
def warn_switched_off(switched_off: tuple[str, ...]) -> None:
    """Log a switched-off posture once per process, however many containers are built.

    The agent tools and the CLI build a container per call, so a warning in
    :func:`build_container` itself would repeat on every call and drown the one line an
    operator needs to see.
    """
    _log.warning("runtime controls switched off: %s", ", ".join(switched_off))


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings.load()
    switched_off = settings.controls.switched_off()
    if switched_off:
        warn_switched_off(switched_off)
    return Container(settings)


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same exact ``adapters:`` entry :meth:`Container._bind` binds from. A missing
    profile binding is an error, so a deployment is never answered about a managed adapter
    that it reached through an implicit fallback.
    A deployment that rebound identity in ``config/settings.yaml`` (the documented on-premises
    path: swap the placeholder for the client's own IdP adapter) is answered about that.

    Constructing is deliberately avoided: the seeded-persona adapter REFUSES to construct
    under an inherited profile, so a posture computed from an instance would be unobtainable
    in one of the exact cases it has to describe.
    """
    binding = settings.adapters.get("identity", {})
    dotted = binding.get(settings.profile)
    if not dotted:
        raise KeyError(f"No identity adapter configured under profile '{settings.profile}'.")
    module_path, _, class_name = dotted.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {dotted!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: neither the profile string nor the presence of a
    service-to-service secret can answer it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
