from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.api._env import load_project_env
from fastapi.middleware.cors import CORSMiddleware

from agent.api.mongo.client import close_mongo, connect_mongo
from agent.api.mongo.repository import ensure_default_customer
from agent.api.phoenix_config import seed_all_customers_phoenix_from_env
from agent.api.routes.meta import router as meta_router
from agent.api.routes.audit import router as audit_router
from agent.api.routes.auth import router as auth_router
from agent.api.routes.customers import router as customers_router
from agent.api.routes.discovery_v2 import router as discovery_v2_router
from agent.api.routes.knowledge_graph import router as knowledge_graph_router
from agent.api.routes.phoenix import router as phoenix_router
from agent.api.storage import ensure_dirs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import logging

    load_project_env()
    ensure_dirs()
    try:
        connect_mongo()
        ensure_default_customer()
        seeded = seed_all_customers_phoenix_from_env()
        if seeded:
            logging.getLogger(__name__).info(
                "Seeded Phoenix config from env for %s existing customer(s)",
                seeded,
            )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "MongoDB not available at startup (%s). API will start; /health shows status.",
            exc,
        )
    yield
    close_mongo()


app = FastAPI(
    title="GovernAI Customer API",
    description="Customer onboarding: system info, tools, data assets, and policies",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(customers_router, prefix="/api/v1")
app.include_router(phoenix_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(knowledge_graph_router, prefix="/api/v1")
app.include_router(discovery_v2_router, prefix="/api/v2")
app.include_router(meta_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    from agent.api.mongo import verify_connection

    try:
        mongo = verify_connection()
    except Exception as exc:
        mongo = {"connected": False, "error": str(exc)}
    return {"status": "ok", "mongo": mongo}


def run() -> None:
    import uvicorn

    from agent.api.port_check import assert_port_available

    load_project_env()
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8800"))
    reload = os.getenv("API_RELOAD", "").lower() in ("1", "true", "yes")
    assert_port_available(host, port)
    # Use import string (not `app` object) so the server binds reliably on Windows.
    # Set API_RELOAD=true only if you need hot reload (can break port binding on Windows).
    uvicorn.run(
        "agent.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )
