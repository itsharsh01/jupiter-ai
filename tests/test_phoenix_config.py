from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from agent.api.phoenix_config import (
    PhoenixSettings,
    default_phoenix_config_from_env,
    get_customer_phoenix_settings,
    seed_customer_phoenix_from_env,
)
from agent.api.schemas import CustomerRecord, PhoenixConfigRecord


@pytest.fixture
def customer_with_phoenix():
    record = CustomerRecord(
        id="cust-1",
        name="Test",
        email="test@example.com",
        phoenix_config=PhoenixConfigRecord(
            api_key="key-123",
            collector_endpoint="https://app.phoenix.arize.com/s/space",
            project_name="demo-project",
            updated_at=datetime.now(timezone.utc),
        ),
    )
    return record


@patch.dict(
    "os.environ",
    {
        "PHOENIX_API_KEY": "env-key",
        "PHOENIX_COLLECTOR_ENDPOINT": "https://app.phoenix.arize.com/s/env",
        "PHOENIX_PROJECT_NAME": "env-project",
    },
    clear=False,
)
def test_default_phoenix_config_from_env():
    config = default_phoenix_config_from_env()
    assert config is not None
    assert config.api_key == "env-key"
    assert config.project_name == "env-project"


@patch("agent.api.phoenix_config.load_customer")
def test_get_customer_phoenix_settings(mock_load, customer_with_phoenix):
    mock_load.return_value = customer_with_phoenix
    settings = get_customer_phoenix_settings("cust-1")
    assert settings is not None
    assert settings.api_key == "key-123"
    assert settings.api_base() == "https://app.phoenix.arize.com/s/space"


@patch("agent.api.phoenix_config.default_phoenix_config_from_env")
@patch("agent.api.phoenix_config.load_customer")
@patch("agent.api.phoenix_config.save_customer")
def test_seed_customer_phoenix_from_env(mock_save, mock_load, mock_default):
    mock_load.return_value = CustomerRecord(
        id="cust-1",
        name="Test",
        email="test@example.com",
    )
    mock_default.return_value = PhoenixConfigRecord(
        api_key="env-key",
        collector_endpoint="https://app.phoenix.arize.com/s/env",
        project_name="env-project",
        updated_at=datetime.now(timezone.utc),
    )
    mock_save.side_effect = lambda record: record

    seeded = seed_customer_phoenix_from_env("cust-1")
    assert seeded is not None
    assert seeded.phoenix_config is not None
    assert seeded.phoenix_config.api_key == "env-key"


@patch("agent.api.routes.phoenix.ensure_customer_phoenix_config")
def test_get_phoenix_config_route_missing(mock_ensure):
    from agent.api.routes.phoenix import get_phoenix_config

    mock_ensure.return_value = CustomerRecord(
        id="cust-1",
        name="Test",
        email="test@example.com",
    )
    with pytest.raises(HTTPException) as exc:
        get_phoenix_config("cust-1")
    assert exc.value.status_code == 404


def test_phoenix_settings_api_base_strips_traces_suffix():
    settings = PhoenixSettings(
        api_key="k",
        collector_endpoint="https://app.phoenix.arize.com/s/space/v1/traces",
        project_name="demo",
    )
    assert settings.api_base() == "https://app.phoenix.arize.com/s/space"
