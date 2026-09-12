"""Terraform and the application name the same house-view store, at the same location.

The class this closes was observed on the deployment in a sibling repository: Terraform created
an Agent Search store at ``us`` while the application queried ``global``, and the first sign was
a 404 at retrieval. Here the store's location is one setting, ``house_views_location`` in
Terraform and ``CIO_HOUSE_VIEWS_LOCATION`` in the application, and this file fails the build when
their defaults, their allowed values or the store and engine ids drift apart.

It reads the Terraform source as text, so it needs no Terraform binary; the plan-level proof is
``infra/terraform/tests/``, run by ``make tf-check``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cio_advisory.config import AGENT_SEARCH_LOCATIONS, HouseViewSettings, Settings
from cio_advisory.envread import ConfiguredEmptyError

REPO_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = REPO_ROOT / "infra" / "terraform"
SETTINGS_FILE = REPO_ROOT / "config" / "settings.yaml"
ENV = "CIO_HOUSE_VIEWS_LOCATION"


def _block(text: str, header: str) -> str:
    """The brace-delimited body following ``header`` in HCL source."""
    start = text.index(header)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening : index + 1]
    raise AssertionError(f"unbalanced block after {header!r}")


def _attribute(block: str, name: str) -> str:
    match = re.search(rf"^\s*{name}\s*=\s*(.+?)\s*(?:#.*)?$", block, re.MULTILINE)
    assert match, f"no {name} attribute"
    return match.group(1)


@pytest.fixture(autouse=True)
def _unset(monkeypatch) -> None:
    monkeypatch.delenv(ENV, raising=False)


def test_the_location_variable_and_the_application_agree_on_default_and_allowed_values() -> None:
    variable = _block((TERRAFORM / "variables.tf").read_text(), 'variable "house_views_location"')
    default = _attribute(variable, "default").strip('"')
    allowed_match = re.search(r"contains\(\[([^\]]*)\],\s*var\.house_views_location\)", variable)
    assert allowed_match, "house_views_location must validate against a literal list"
    allowed = tuple(re.findall(r'"([^"]+)"', allowed_match.group(1)))

    assert allowed == AGENT_SEARCH_LOCATIONS
    assert default == HouseViewSettings().location
    yaml_default = re.search(rf"\$\{{{ENV}:-([^}}]*)\}}", SETTINGS_FILE.read_text())
    assert yaml_default, f"config/settings.yaml must read the location from {ENV}"
    assert yaml_default.group(1) == default
    assert Settings.load(SETTINGS_FILE).house_views.location == default


def test_the_store_and_engine_are_created_where_the_variable_says_under_the_ids_the_app_reads() -> (
    None
):
    source = (TERRAFORM / "house_views.tf").read_text()
    store = _block(source, 'resource "google_discovery_engine_data_store" "house_views"')
    engine = _block(source, 'resource "google_discovery_engine_search_engine" "house_views"')
    loaded = Settings.load(SETTINGS_FILE).house_views

    assert _attribute(store, "location") == "var.house_views_location"
    assert (
        _attribute(engine, "location") == "google_discovery_engine_data_store.house_views.location"
    )
    assert _attribute(store, "data_store_id").strip('"') == loaded.data_store_id
    assert _attribute(engine, "engine_id").strip('"') == loaded.engine_id


def test_the_location_is_one_three_state_setting(monkeypatch) -> None:
    assert Settings.load(SETTINGS_FILE).house_views.location == "us"

    monkeypatch.setenv(ENV, "eu")
    assert Settings.load(SETTINGS_FILE).house_views.location == "eu"

    monkeypatch.setenv(ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=ENV):
        Settings.load(SETTINGS_FILE)

    monkeypatch.setenv(ENV, "asia-southeast1")
    with pytest.raises(ValueError, match="not an Agent Search location"):
        Settings.load(SETTINGS_FILE)
