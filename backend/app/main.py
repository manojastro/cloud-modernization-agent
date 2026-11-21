"""FastAPI application factory.

CORS from env, safe error responses (no stack traces to clients), Prometheus metrics,
and the static SPA mounted LAST so API routes win.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# The estate simulator package lives at <root>/simulator; ensure it is importable
# regardless of the working directory uvicorn is launched from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.workflow.engine import WorkflowViolation  # noqa: E402

logging.basicConfig(level=get_settings().log_level.upper())
logger = logging.getLogger("cloud-modernization-agent")

FRONTEND_DIR = PROJECT_ROOT / "frontend"

SAFE_DETAIL = "internal error; see server logs"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version,
                  docs_url="/docs", redoc_url=None)

    # CORS from env (comma-separated origins)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    # ---- safe error handlers
    @app.exception_handler(WorkflowViolation)
    async def _workflow_violation_handler(request: Request, exc: WorkflowViolation):
        return JSONResponse(status_code=409,
                            content={"error": "workflow_violation",
                                     "detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422,
                            content={"error": "validation_error",
                                     "detail": str(exc.errors()[:3])})

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled error on %s: %s", request.url.path, exc)
        return JSONResponse(status_code=500,
                            content={"error": "internal_error", "detail": SAFE_DETAIL})

    # ---- routers
    from app.api.routes_assessment import router as assessment_router
    from app.api.routes_meta import router as meta_router
    from app.api.routes_misc import router as misc_router
    from app.api.routes_portfolio import router as portfolio_router
    from app.api.routes_simulator import router as simulator_router
    from app.api.routes_strategy import router as strategy_router
    from app.api.routes_targetarch import router as targetarch_router
    from app.api.routes_waves import router as waves_router

    app.include_router(meta_router)
    app.include_router(simulator_router)
    app.include_router(portfolio_router)
    app.include_router(assessment_router)
    app.include_router(strategy_router)
    app.include_router(waves_router)
    app.include_router(targetarch_router)
    app.include_router(misc_router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        logger.info("%s v%s started (llm_mode=%s)", settings.app_name,
                    settings.version, settings.llm_mode)

    # ---- static SPA LAST so /api and /health etc. take precedence
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
                  name="frontend")
    else:  # pragma: no cover - dev convenience only
        logger.warning("frontend directory not found at %s; SPA not served",
                       FRONTEND_DIR)

    return app


app = create_app()
