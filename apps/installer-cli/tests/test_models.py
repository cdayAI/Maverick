"""Wizard model-catalog invariants."""
from __future__ import annotations

from maverick_installer import models


def test_every_provider_has_required_fields():
    for prov_id, info in models.PROVIDERS.items():
        assert "label" in info, f"{prov_id} missing label"
        assert "status" in info, f"{prov_id} missing status"
        assert info["status"] in ("ready", "planned")
        assert isinstance(info["models"], list)
        assert len(info["models"]) > 0
        for m in info["models"]:
            assert "id" in m
            assert "notes" in m


def test_default_for_every_role():
    for role, _ in models.ROLES:
        spec = models.default_for_role(role)
        assert ":" in spec, f"{role} default missing provider prefix: {spec}"
        provider, _model = spec.split(":", 1)
        assert provider in models.PROVIDERS, f"{role} -> unknown provider {provider}"


def test_all_providers_now_ready():
    # Sanity check: multi-provider dispatch landed; nothing should be 'planned'.
    for prov_id, info in models.PROVIDERS.items():
        assert info["status"] == "ready", (
            f"{prov_id} still marked planned; update models.py"
        )
