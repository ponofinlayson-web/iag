"""IAG application assembly."""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.settings import Settings
from app.routers import audit, auth, campaigns, dashboard, entitlements, identities, reminders, reviews, sod, sources
settings = Settings()
settings.validate_secrets()
settings.validate_smtp()
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format=json.dumps({"ts": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "msg": "%(message)s"}),
)
logger = logging.getLogger("iag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-replica reminder worker (resilience contract 4: the app
    is the only writer; no cron, no sidecar schedulers). Skipped under test:
    SessionLocal targets the production URL and tests drive run_pass with
    their own factory."""
    if settings.env == "test":
        yield
        return
    from app.core.email_worker import worker_loop
    task = asyncio.create_task(worker_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="IAG", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.include_router(auth.router)
app.include_router(identities.router)
app.include_router(sources.router)
app.include_router(entitlements.router)
app.include_router(campaigns.router)
app.include_router(reviews.router)
app.include_router(sod.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(reminders.router)
@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "iag-api", "version": "0.1.0"}
_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="spa")
