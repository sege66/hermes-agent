"""Local (ki66) additions split out of the upstream-owned test_xai_curated_models.py."""

from hermes_cli.models import _PROVIDER_MODELS
from hermes_cli.models_catalog_static import _XAI_TOP_MODEL


def test_xai_headline_is_default_pin():
    models = _PROVIDER_MODELS["xai-oauth"]
    assert models[0] == _XAI_TOP_MODEL
