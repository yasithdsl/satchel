"""Workspace wiring: every member imports and depends on satchel-core."""

import importlib
import importlib.metadata

import pytest


def test_all_packages_importable():
    for name in [
        "satchel_core",
        "satchel_vault",
        "satchel_signer",
        "satchel_agent",
        "satchel_marketplace",
        "satchel_laptop",
    ]:
        assert importlib.import_module(name)


@pytest.mark.parametrize(
    "dist",
    [
        "satchel-vault",
        "satchel-signer",
        "satchel-agent",
        "satchel-marketplace",
        "satchel-laptop",
    ],
)
def test_member_depends_on_core(dist):
    requires = importlib.metadata.requires(dist) or []
    assert any(r.startswith("satchel-core") for r in requires)
