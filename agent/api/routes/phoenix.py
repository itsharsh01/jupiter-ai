from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from agent.api.phoenix_config import (
    ensure_customer_phoenix_config,
    get_customer_phoenix_settings,
    save_customer_phoenix_config,
    seed_all_customers_phoenix_from_env,
    seed_customer_phoenix_from_env,
)
from agent.api.schemas import (
    MessageResponse,
    PhoenixConfigCredentialsResponse,
    PhoenixConfigRecord,
    PhoenixConfigResponse,
    PhoenixConfigUpdate,
)
from agent.api.storage import load_customer

router = APIRouter(prefix="/customers", tags=["phoenix"])


def _summary(customer_id: str, config: PhoenixConfigRecord) -> PhoenixConfigResponse:
    return PhoenixConfigResponse(
        customer_id=customer_id,
        collector_endpoint=config.collector_endpoint,
        project_name=config.project_name,
        api_key_set=bool(config.api_key.strip()),
        updated_at=config.updated_at,
    )


def _credentials(customer_id: str, config: PhoenixConfigRecord) -> PhoenixConfigCredentialsResponse:
    return PhoenixConfigCredentialsResponse(
        customer_id=customer_id,
        api_key=config.api_key,
        collector_endpoint=config.collector_endpoint,
        project_name=config.project_name,
        updated_at=config.updated_at,
    )


@router.get("/{customer_id}/phoenix", response_model=PhoenixConfigResponse)
def get_phoenix_config(customer_id: str) -> PhoenixConfigResponse:
    record = ensure_customer_phoenix_config(customer_id)
    if record.phoenix_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phoenix config not set for this customer",
        )
    return _summary(customer_id, record.phoenix_config)


@router.get("/{customer_id}/phoenix/credentials", response_model=PhoenixConfigCredentialsResponse)
def get_phoenix_credentials(customer_id: str) -> PhoenixConfigCredentialsResponse:
    """Return full Phoenix credentials for GovernAI SDK / agent runtimes."""
    record = ensure_customer_phoenix_config(customer_id)
    if record.phoenix_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phoenix config not set for this customer",
        )
    return _credentials(customer_id, record.phoenix_config)


@router.put("/{customer_id}/phoenix", response_model=PhoenixConfigResponse)
def upsert_phoenix_config(customer_id: str, body: PhoenixConfigUpdate) -> PhoenixConfigResponse:
    load_customer(customer_id)
    config = PhoenixConfigRecord(
        **body.model_dump(),
        updated_at=datetime.now(timezone.utc),
    )
    record = save_customer_phoenix_config(customer_id, config)
    assert record.phoenix_config is not None
    return _summary(customer_id, record.phoenix_config)


@router.post("/{customer_id}/phoenix/seed-from-env", response_model=PhoenixConfigResponse)
def seed_phoenix_from_env(customer_id: str) -> PhoenixConfigResponse:
    record = seed_customer_phoenix_from_env(customer_id)
    if record is None or record.phoenix_config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform PHOENIX_* env vars are not configured on the server",
        )
    return _summary(customer_id, record.phoenix_config)


@router.post("/phoenix/seed-all-from-env", response_model=MessageResponse)
def seed_all_phoenix_from_env() -> MessageResponse:
    count = seed_all_customers_phoenix_from_env()
    return MessageResponse(
        message=f"Seeded Phoenix config from env for {count} customer(s)",
        data={"updated": count},
    )
