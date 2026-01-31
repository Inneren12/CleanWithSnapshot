import importlib

import pytest
from pydantic import ValidationError

from app.domain.feature_modules.schemas import FeatureOverrideConfig


def test_feature_modules_schema_import_smoke():
    module = importlib.import_module("app.domain.feature_modules.schemas")
    assert getattr(module, "FeatureOverrideConfig") is FeatureOverrideConfig


def test_feature_override_config_valid_payload():
    payload = FeatureOverrideConfig(percentage=25)
    assert payload.percentage == 25
    assert payload.enabled is None


def test_feature_override_config_rejects_empty_payload():
    with pytest.raises(ValidationError, match="override must include enabled or percentage"):
        FeatureOverrideConfig()


def test_feature_override_config_rejects_invalid_percentage():
    with pytest.raises(ValidationError, match="percentage must be one of 0, 10, 25, 50, or 100"):
        FeatureOverrideConfig(percentage=33)
