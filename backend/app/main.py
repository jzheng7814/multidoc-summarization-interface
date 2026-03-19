from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import init_db
from app.eventing import get_event_producer, init_event_system, shutdown_event_system
from app.services.cluster_extraction import validate_cluster_runtime_prerequisites
from app.services.cluster_summary import validate_cluster_summary_runtime_prerequisites

settings = get_settings()
producer = get_event_producer(__name__)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*" if settings.environment == "development" else ""],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def startup_event() -> None:
    validate_cluster_runtime_prerequisites()
    validate_cluster_summary_runtime_prerequisites()
    init_db()
    await init_event_system(settings)
    producer.info(
        "Backend startup",
        {
            "app_name": settings.app_name,
            "environment": settings.environment,
            "cluster_run_mode": settings.cluster_run_mode,
        },
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    producer.info("Backend shutdown")
    await shutdown_event_system()
