"""A house view naming a tenant reaches only that tenant's briefings; an untagged one is public."""

from __future__ import annotations

from cio_advisory.domain.entitlements import visible_house_views
from cio_advisory.domain.identity import Principal
from cio_advisory.domain.models import AssetClass, HouseView, Stance


def _view(view_id: str, tenant: str = "") -> HouseView:
    return HouseView(
        id=view_id,
        theme=view_id,
        stance=Stance.NEUTRAL,
        asset_class=AssetClass.EQUITY,
        tenant=tenant,
    )


OWN = _view("own", "fictional-bank")
FOREIGN = _view("foreign", "fictional-bank-other")
PUBLIC = _view("public")


def _principal(tenant: str) -> Principal:
    return Principal(subject="rm@bank.test", principals=("group:cio-analyst",), tenant=tenant)


def test_a_principal_sees_its_own_tenants_views_and_public_ones_in_retrieval_order() -> None:
    assert visible_house_views(_principal("fictional-bank"), [FOREIGN, OWN, PUBLIC]) == [
        OWN,
        PUBLIC,
    ]


def test_a_principal_with_no_tenant_sees_public_views_only() -> None:
    assert visible_house_views(_principal(""), [OWN, FOREIGN, PUBLIC]) == [PUBLIC]


def test_another_tenants_views_alone_leave_nothing() -> None:
    assert visible_house_views(_principal("fictional-bank"), [FOREIGN]) == []
