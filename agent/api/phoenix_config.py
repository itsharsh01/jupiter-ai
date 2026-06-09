from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.api.mongo.repository import load_customer, save_customer
from agent.api.schemas import CustomerRecord, PhoenixConfigRecord


@dataclass(frozen=True)
class PhoenixSettings:
    api_key: str
    collector_endpoint: str
    project_name: str

    def configured(self) -> bool:
        return bool(self.api_key.strip() and self.collector_endpoint.strip())

    def api_base(self) -> str | None:
        endpoint = self.collector_endpoint.strip().rstrip("/")
        if not endpoint:
            return None
        if endpoint.endswith("/v1/traces"):
            return endpoint[: -len("/v1/traces")]
        return endpoint


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_phoenix_config_from_env() -> PhoenixConfigRecord | None:
    """Server bootstrap only — copies platform Phoenix env into a customer record."""
    api_key = os.getenv("PHOENIX_API_KEY", "").strip()
    collector_endpoint = (
        os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
        or os.getenv("PHOENIX_BASE_URL")
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or ""
    ).strip()
    if not api_key or not collector_endpoint:
        return None
    project_name = os.getenv("PHOENIX_PROJECT_NAME", "governai").strip() or "governai"
    return PhoenixConfigRecord(
        api_key=api_key,
        collector_endpoint=collector_endpoint,
        project_name=project_name,
        updated_at=_utc_now(),
    )


def _to_settings(record: PhoenixConfigRecord) -> PhoenixSettings:
    return PhoenixSettings(
        api_key=record.api_key,
        collector_endpoint=record.collector_endpoint,
        project_name=record.project_name,
    )


def get_customer_phoenix_settings(customer_id: str) -> PhoenixSettings | None:
    record = load_customer(customer_id)
    if record.phoenix_config is None:
        return None
    settings = _to_settings(record.phoenix_config)
    return settings if settings.configured() else None


def save_customer_phoenix_config(
    customer_id: str,
    config: PhoenixConfigRecord,
) -> CustomerRecord:
    record = load_customer(customer_id)
    record.phoenix_config = config
    return save_customer(record)


def seed_customer_phoenix_from_env(customer_id: str) -> CustomerRecord | None:
    """Copy platform env Phoenix settings onto a customer if missing."""
    record = load_customer(customer_id)
    if record.phoenix_config is not None:
        return record
    env_config = default_phoenix_config_from_env()
    if env_config is None:
        return None
    record.phoenix_config = env_config
    return save_customer(record)


def ensure_customer_phoenix_config(customer_id: str) -> CustomerRecord:
    seeded = seed_customer_phoenix_from_env(customer_id)
    return seeded if seeded is not None else load_customer(customer_id)


def seed_all_customers_phoenix_from_env() -> int:
    """Seed Phoenix config for every customer missing it. Returns count updated."""
    from agent.api.mongo.repository import list_customers

    updated = 0
    for customer in list_customers():
        if customer.phoenix_config is not None:
            continue
        if seed_customer_phoenix_from_env(customer.id) is not None:
            updated += 1
    return updated
