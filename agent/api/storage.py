from __future__ import annotations

import os
from pathlib import Path

from agent.api.mongo.repository import (
    delete_customer as mongo_delete_customer,
)
from agent.api.mongo.repository import (
    list_customers,
    load_customer,
    save_customer,
)
from agent.api.schemas import CustomerRecord

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"


def _uploads_base() -> Path:
    override = os.getenv("GOVERN_UPLOADS_DIR", "").strip()
    if override:
        return Path(override)
    # App Engine Standard: app code under /workspace is read-only; only /tmp is writable.
    if os.getenv("GAE_ENV") == "standard":
        return Path("/tmp/governai/uploads")
    return DATA_DIR / "uploads"


UPLOADS_DIR = _uploads_base()


def ensure_dirs() -> None:
    global UPLOADS_DIR
    for candidate in (_uploads_base(), Path("/tmp/governai/uploads")):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            UPLOADS_DIR = candidate
            return
        except OSError:
            continue
    raise OSError("No writable uploads directory found")


def customer_uploads_dir(customer_id: str) -> Path:
    path = UPLOADS_DIR / customer_id / "policies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def discovery_uploads_dir(session_id: str) -> Path:
    path = UPLOADS_DIR / "discovery" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "DATA_DIR",
    "UPLOADS_DIR",
    "CustomerRecord",
    "customer_uploads_dir",
    "delete_customer",
    "ensure_dirs",
    "list_customers",
    "load_customer",
    "save_customer",
]


def delete_customer(customer_id: str) -> bool:
    return mongo_delete_customer(customer_id)
