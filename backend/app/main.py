"""IAG application assembly."""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.settings import Settings
from app.core.scim import ScimError
from app.routers import apikeys, audit, auth, campaigns, dashboard, entitlements, identities, remediation, reminders, reviews, risk, scim, sod, sources, syncs
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
    """Start the in-replica workers (resilience contract 4: the app is the
    only writer; no cron, no sidecar schedulers). Skipped under test:
    SessionLocal targets the production URL and tests drive run_pass with
    their own factory."""
    if settings.env == "test":
        yield
        return
    from app.core.email_worker import worker_loop
    from app.core.sync_worker import connector_worker_loop
    from app.core.remediation_worker import remediation_worker_loop
    task = asyncio.create_task(worker_loop())
    sync_task = asyncio.create_task(connector_worker_loop())
    remediation_task = asyncio.create_task(remediation_worker_loop())
    yield
    task.cancel()
    sync_task.cancel()
    remediation_task.cancel()
    for t in (task, sync_task, remediation_task):
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="IAG", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)


def _openapi_with_bearer() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    app.openapi_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schemes = app.openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes["bearerAuth"] = {"type": "http", "scheme": "bearer",
                             "description": "API key in the form iag_{id}_{token} (read-only machine access)"}
    return app.openapi_schema


app.openapi = _openapi_with_bearer
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
app.include_router(syncs.router)
app.include_router(entitlements.router)
app.include_router(campaigns.router)
app.include_router(reviews.router)
app.include_router(sod.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(reminders.router)
app.include_router(remediation.router)
app.include_router(apikeys.router)
app.include_router(risk.router)
app.include_router(scim.router)


@app.exception_handler(ScimError)
async def scim_error_handler(request: Request, exc: ScimError) -> JSONResponse:
    """RFC 7644 error envelope for every SCIM-surface failure."""
    return JSONResponse(status_code=exc.status, content=exc.envelope(), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """SCIM paths render 422s as 400 SCIM envelopes (protocol surface);
    every other path keeps FastAPI's default response, byte-identical.
    Returns (never raises - a raise inside a handler escapes to the 500
    middleware, it does not re-enter this app's handlers)."""
    if request.url.path.startswith("/api/scim/"):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []))
        envelope = ScimError(400, f"Invalid request body at {where}: {first.get('msg', 'validation error')}")
        return JSONResponse(status_code=envelope.status, content=envelope.envelope())
    return await request_validation_exception_handler(request, exc)
@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "iag-api", "version": "0.1.0"}
_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="spa")
