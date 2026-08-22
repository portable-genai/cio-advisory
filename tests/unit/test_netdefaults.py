"""Fail-closed network defaults (C5).

The API bound 0.0.0.0 unconditionally and the CORS fallback trusted the dev origins in
every profile (C5 PARTIAL). Both are now wired through the shared ``hex-service-kit``
rules; these tests prove THIS repo's wiring (each was red against the pre-adoption
behaviour).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cio_advisory.api import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def _origins_for_profile(monkeypatch: pytest.MonkeyPatch, profile: str) -> list[str]:
    import dataclasses

    monkeypatch.delenv("CIO_CORS_ORIGINS", raising=False)
    # profile_explicit marks the profile as DELIBERATELY named. The CORS allowlist is a
    # RELAXATION, so it keys off exposure_profile, which withholds everything from a run
    # that never named a profile. Replacing `profile` alone left that flag to whatever
    # Settings.load() found, so this asserted the relaxed posture only because `make test`
    # exports CIO_PROFILE. Setting it here makes the test say what it means and pass
    # under a bare pytest too. The unconsented case has its own test below.
    settings = dataclasses.replace(
        app_module.deps.get_settings(), profile=profile, profile_explicit=True
    )
    monkeypatch.setattr(app_module.deps, "get_settings", lambda: settings)
    return app_module._cors_origins()


def test_cors_fallback_only_under_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _origins_for_profile(monkeypatch, "local") == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    # A secure deploy that forgets the allowlist gets NO cross-origin trust (was: dev
    # origins with credentials in every profile).
    assert _origins_for_profile(monkeypatch, "gcp") == []
    assert _origins_for_profile(monkeypatch, "platform") == []


def test_explicit_allowlist_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIO_CORS_ORIGINS", "https://tenant.example")
    assert app_module._cors_origins() == ["https://tenant.example"]


def test_local_profile_refuses_non_loopback_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    from hex_service_kit import InsecureBindError, resolve_bind_host

    monkeypatch.setenv("CIO_API_HOST", "0.0.0.0")
    monkeypatch.delenv("CIO_ALLOW_INSECURE_DEMO", raising=False)
    with pytest.raises(InsecureBindError):
        resolve_bind_host(
            "local",
            host_env="CIO_API_HOST",
            insecure_demo_env="CIO_ALLOW_INSECURE_DEMO",
        )


def test_api_still_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app_module.app, client=("127.0.0.1", 50000))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in response.headers


def test_a_run_that_never_named_a_profile_gets_no_cross_origin_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relaxation keys off a deliberate choice, not off the default landing on local."""
    import dataclasses

    monkeypatch.delenv("CIO_CORS_ORIGINS", raising=False)
    settings = dataclasses.replace(
        app_module.deps.get_settings(), profile="local", profile_explicit=False
    )
    monkeypatch.setattr(app_module.deps, "get_settings", lambda: settings)
    assert app_module._cors_origins() == []


# The wildcard refusal. Both origin policies documented "never *" in a comment and then
# passed whatever the operator set straight through, so `CIO_CORS_ORIGINS=*` produced an
# allowlist of every origin WITH credentials, and `CIO_FRAME_ANCESTORS=*` let any parent
# page frame the console. A rule stated in a comment is a rule nothing enforces.


def test_a_wildcard_cors_allowlist_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIO_CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._cors_origins()


def test_a_wildcard_hiding_inside_an_origin_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """``https://*.example`` is an allowlist of every subdomain, including one an attacker took."""
    monkeypatch.setenv("CIO_CORS_ORIGINS", "https://tenant.example,https://*.example")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._cors_origins()


def test_a_wildcard_frame_ancestor_is_refused() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        app_module._frame_ancestors("*")
    with pytest.raises(ValueError, match="wildcard"):
        app_module._frame_ancestors("'self' https://*.parent.example")


def test_a_legitimate_allowlist_and_the_three_states_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal adds ONE case. Unset, emptied and a named allowlist must all still hold."""
    assert app_module._frame_ancestors(None) == "'self'"
    assert app_module._frame_ancestors("") == "'none'"
    assert app_module._frame_ancestors("   ") == "'none'"
    assert app_module._frame_ancestors("https://parent.example") == "https://parent.example"
    monkeypatch.setenv("CIO_CORS_ORIGINS", "")
    assert app_module._cors_origins() == []
    monkeypatch.setenv("CIO_CORS_ORIGINS", "https://tenant.example, https://other.example")
    assert app_module._cors_origins() == ["https://tenant.example", "https://other.example"]


@pytest.mark.parametrize("variable", ["CIO_CORS_ORIGINS", "CIO_FRAME_ANCESTORS"])
def test_a_wildcard_refuses_at_boot_and_not_on_some_later_request(variable: str) -> None:
    """Importing the app must fail, so a wildcard cannot reach a running service at all.

    A refusal raised on the first cross-origin request would leave the misconfiguration live
    until traffic found it, and a health check would have called the deployment good.
    """
    completed = subprocess.run(
        [sys.executable, "-c", "import cio_advisory.api.app"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": "src", "CIO_PROFILE": "local", variable: "*"},
        check=False,
        timeout=300,
    )
    assert completed.returncode != 0, f"the app imported with {variable}=*"
    assert "wildcard" in completed.stderr, completed.stderr
