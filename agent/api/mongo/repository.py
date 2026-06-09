from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, status

from agent.api.schemas import CustomerRecord
from agent.auth.tokens import hash_password

from .client import get_customers_collection


def _seed_phoenix_if_missing(record: CustomerRecord) -> CustomerRecord:
    from agent.api.phoenix_config import default_phoenix_config_from_env

    if record.phoenix_config is not None:
        return record
    env_config = default_phoenix_config_from_env()
    if env_config is None:
        return record
    record.phoenix_config = env_config
    return record


def save_customer(record: CustomerRecord) -> CustomerRecord:
    collection = get_customers_collection()
    record = _seed_phoenix_if_missing(record)
    doc = record.model_dump(mode="json")
    collection.replace_one({"id": record.id}, doc, upsert=True)
    return record


def load_customer(customer_id: str) -> CustomerRecord:
    collection = get_customers_collection()
    doc = collection.find_one({"id": customer_id})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found",
        )
    doc.pop("_id", None)
    return CustomerRecord.model_validate(doc)


def get_customer_by_email(email: str) -> CustomerRecord | None:
    collection = get_customers_collection()
    doc = collection.find_one({"email": email.lower().strip()})
    if doc is None:
        return None
    doc.pop("_id", None)
    return CustomerRecord.model_validate(doc)


def register_customer(
    *,
    email: str,
    password: str,
    name: str | None = None,
    company: str | None = None,
) -> CustomerRecord:
    normalized_email = email.lower().strip()
    if get_customer_by_email(normalized_email) is not None:
        raise ValueError("Email already registered")

    record = CustomerRecord(
        name=(name or normalized_email.split("@", 1)[0]).strip(),
        email=normalized_email,
        company=company,
        password_hash=hash_password(password),
    )
    return save_customer(record)


def count_customers_with_password() -> int:
    collection = get_customers_collection()
    return collection.count_documents({"password_hash": {"$exists": True, "$ne": None}})


def ensure_default_customer() -> CustomerRecord | None:
    """Seed demo login customer when no authenticated customers exist."""
    if count_customers_with_password() > 0:
        return None

    email = os.getenv("GOVERN_AUTH_DEMO_EMAIL", "root@gov.os").lower().strip()
    password = os.getenv("GOVERN_AUTH_DEMO_PASSWORD", "governai-dev")
    existing = get_customer_by_email(email)
    if existing is not None:
        if existing.password_hash:
            return None
        existing.password_hash = hash_password(password)
        return save_customer(existing)

    return register_customer(
        email=email,
        password=password,
        name="Root Operator",
        company="GovernAI Demo",
    )


def list_customers() -> list[CustomerRecord]:
    collection = get_customers_collection()
    records: list[CustomerRecord] = []
    for doc in collection.find().sort("created_at", -1):
        doc.pop("_id", None)
        records.append(CustomerRecord.model_validate(doc))
    return records


def delete_customer(customer_id: str) -> bool:
    collection = get_customers_collection()
    result = collection.delete_one({"id": customer_id})
    return result.deleted_count > 0


def link_discovery_session(customer_id: str, session_id: str) -> CustomerRecord:
    record = load_customer(customer_id)
    record.discovery_session_id = session_id
    return save_customer(record)
