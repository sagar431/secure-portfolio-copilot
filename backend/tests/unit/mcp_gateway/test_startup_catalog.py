import pytest

import app.main as main_module
from app.core.config import Settings
from app.mcp_gateway.adapters import (
    SearchAuthorizedDocumentsAdapter,
    validate_production_tool_catalog,
)
from app.mcp_gateway.contracts import GetDocumentExcerptInput
from app.mcp_gateway.errors import GatewayConfigurationError


def test_production_catalog_is_validated_at_application_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate_production_tool_catalog()

    monkeypatch.setattr(SearchAuthorizedDocumentsAdapter, "input_model", GetDocumentExcerptInput)
    with pytest.raises(GatewayConfigurationError, match="INPUT_SCHEMA_MISMATCH"):
        validate_production_tool_catalog()


def test_create_app_propagates_catalog_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_startup() -> None:
        raise GatewayConfigurationError("CAPABILITY_MISMATCH")

    monkeypatch.setattr(main_module, "validate_production_tool_catalog", fail_startup)
    with pytest.raises(GatewayConfigurationError, match="CAPABILITY_MISMATCH"):
        main_module.create_app(Settings(_env_file=None, app_env="test"))
