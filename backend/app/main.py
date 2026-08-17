"""IAG application assembly."""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.settings import Settings
from app.routers import audit, auth, campaigns, dashboard, entitlements, identities, reviews, sources
settings = Settings()
settings.validate_secrets()
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format=json.dumps({"ts": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "msg": "%(message)s"}),
)
logger = logging.getLogger("iag")
app = FastAPI(title="IAG", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
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
app.include_router(audit.router)
app.include_router(dashboard.router)
@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "iag-api", "version": "0.1.0"}
_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="spa")
