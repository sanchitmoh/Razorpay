from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.security import RequestIdMiddleware, RequestLoggingMiddleware
from app.db.database import engine
from app.schemas.responses import APIErrorDetail, APIErrorResponse, build_metadata_from_request

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the FastAPI app."""
    app.state.start_time = time.time()
    yield
    await engine.dispose()


app = FastAPI(
    title="Reconciliation Agent API",
    description="Three-way reconciliation: Razorpay payments ↔ Bank statement ↔ Internal ledger",
    version="1.0.0",
    lifespan=lifespan,
)

# App state initialization
app.state.start_time = time.time()

# Security & Observability Middlewares (outermost executed first)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)

# CORS — configured via CORS_ALLOWED_ORIGINS (defaults to "*" for demo/dev)
cors_origins = settings.cors_origins_list
allow_credentials = False if cors_origins == ["*"] else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Exception Handlers for Structured Error Responses & Metadata
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    meta = build_metadata_from_request(request)
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        err_info = exc.detail["error"]
        code = err_info.get("code", "HTTP_ERROR")
        message = err_info.get("message", str(exc.detail))
        field = err_info.get("field")
        detail_obj = exc.detail
    elif isinstance(exc.detail, dict):
        code = exc.detail.get("code", "HTTP_ERROR")
        message = exc.detail.get("message", str(exc.detail))
        field = exc.detail.get("field")
        detail_obj = exc.detail
    else:
        code = "HTTP_ERROR" if exc.status_code != 401 else "UNAUTHORIZED"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 429:
            code = "RATE_LIMITED"
        elif exc.status_code == 400:
            code = "BAD_REQUEST"
        elif exc.status_code == 503:
            code = "SERVICE_UNAVAILABLE"
        message = str(exc.detail)
        field = None
        detail_obj = message

    content = {
        "detail": detail_obj,
        "error": {
            "code": code,
            "message": message,
            "field": field,
        },
        "metadata": meta.model_dump(mode="json"),
    }

    headers = getattr(exc, "headers", None) or {}
    if "X-Request-ID" not in headers:
        headers["X-Request-ID"] = meta.request_id

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=headers,
    )


from fastapi.encoders import jsonable_encoder


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    meta = build_metadata_from_request(request)
    errors = exc.errors()
    first_err = errors[0] if errors else {}
    loc = " -> ".join(str(l) for l in first_err.get("loc", []))
    msg = first_err.get("msg", "Validation error")

    content = {
        "detail": jsonable_encoder(exc.errors()),
        "error": {
            "code": "VALIDATION_ERROR",
            "message": f"{msg} at {loc}" if loc else msg,
            "field": loc or None,
        },
        "metadata": meta.model_dump(mode="json"),
    }
    headers = {"X-Request-ID": meta.request_id}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=content,
        headers=headers,
    )


from app.api.routes import batches, health, qa, webhooks  # noqa: E402

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(batches.router, prefix="/api/v1", tags=["batches"])
app.include_router(qa.router, prefix="/api/v1", tags=["qa"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])

# Static files and data mounts for demo dashboard
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
static_dir = os.path.join(base_dir, "static")
data_dir = os.path.join(base_dir, "data")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

if os.path.exists(data_dir):
    app.mount("/data", StaticFiles(directory=data_dir), name="data")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Reconciliation Agent API is online. Visit /docs for OpenAPI specifications."}
