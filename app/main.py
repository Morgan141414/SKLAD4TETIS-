from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.dependencies import get_database
from app.api.routes import router
from app.core.config import get_settings
from app.services.background_jobs import PeriodicJobRunner, WarehouseBackgroundJobs
from app.services.warehouse import WarehouseService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    runner: PeriodicJobRunner | None = None
    if settings.background_jobs_enabled:
        jobs = WarehouseBackgroundJobs(
            lambda: WarehouseService(get_database()),
            expiry_days=settings.background_jobs_expiry_days,
            actor_id=settings.background_jobs_actor_id,
        )
        runner = PeriodicJobRunner(
            jobs,
            interval_seconds=settings.background_jobs_interval_seconds,
        )
        app.state.background_job_runner = runner
        runner.start()
    try:
        yield
    finally:
        if runner:
            await runner.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Medical warehouse accounting service",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(router, prefix="/sklad")
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    if frontend_dir.exists():
        app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")
        app.mount("/sklad", StaticFiles(directory=frontend_dir, html=True), name="frontend_sklad")

        @app.get("/app", include_in_schema=False)
        def frontend_redirect():
            return RedirectResponse(url="/app/")

        @app.get("/sklad", include_in_schema=False)
        def sklad_frontend_redirect():
            return RedirectResponse(url="/sklad/")

    return app


app = create_app()
