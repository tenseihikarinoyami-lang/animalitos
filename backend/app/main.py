import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.api import admin, auth, monitoring
from app.core.config import settings
from app.core.logging import configure_logging, get_logger, log_event
from app.core.runtime import (
    mark_database_status,
    mark_startup_phase,
    refresh_database_status,
    register_startup_issue,
    reset_startup_issues,
    runtime_status_snapshot,
)
from app.core.security import get_password_hash
from app.services.analytics import analytics_service
from app.services.database import db_service
from app.services.monitoring import monitoring_service
from app.services.schedule import utc_now


scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.app_timezone))
logger = get_logger(__name__)


def ensure_admin_user() -> None:
    admin_user = db_service.get_user(settings.bootstrap_admin_username)
    if admin_user:
        if admin_user.get("role") != "admin":
            admin_user["role"] = "admin"
            db_service.save_user(admin_user)
        return

    bootstrap_password = settings.bootstrap_admin_password
    if not bootstrap_password and settings.allow_insecure_dev_admin and not settings.is_production:
        bootstrap_password = "admin123"

    if not bootstrap_password:
        log_event(
            logger,
            level=30,
            event="admin_bootstrap_skipped",
            reason="no_bootstrap_password",
            username=settings.bootstrap_admin_username,
        )
        return

    db_service.save_user(
        {
            "username": settings.bootstrap_admin_username,
            "email": settings.bootstrap_admin_email,
            "password": get_password_hash(bootstrap_password),
            "full_name": settings.bootstrap_admin_full_name,
            "role": "admin",
            "is_active": True,
        }
    )
    log_event(
        logger,
        level=20,
        event="admin_bootstrap_created",
        username=settings.bootstrap_admin_username,
        insecure_default=bool(settings.allow_insecure_dev_admin and not settings.is_production),
    )


async def scheduled_refresh() -> None:
    await monitoring_service.run_due_scheduler_cycle(trigger="internal-scheduler", notify=True)


async def scheduled_daily_summary() -> None:
    await monitoring_service.send_daily_summary()


async def scheduled_possible_results() -> None:
    await monitoring_service.send_today_possible_results()


async def scheduled_today_analysis_opening() -> None:
    await monitoring_service.send_today_analysis_report(phase="apertura")


async def scheduled_today_analysis_midday() -> None:
    await monitoring_service.send_today_analysis_report(phase="media-jornada")


async def scheduled_weekly_recovery_backfill() -> None:
    await monitoring_service.run_weekly_recovery_backfill()


def configure_internal_scheduler() -> None:
    if settings.use_external_scheduler:
        return
    if scheduler.running:
        return

    scheduler.add_job(
        scheduled_refresh,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="scheduled_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_possible_results,
        trigger=CronTrigger(hour=8, minute=5, timezone=ZoneInfo(settings.app_timezone)),
        id="scheduled_possible_results",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_today_analysis_opening,
        trigger=CronTrigger(hour=9, minute=35, timezone=ZoneInfo(settings.app_timezone)),
        id="scheduled_today_analysis_opening",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_today_analysis_midday,
        trigger=CronTrigger(hour=13, minute=35, timezone=ZoneInfo(settings.app_timezone)),
        id="scheduled_today_analysis_midday",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_daily_summary,
        trigger=CronTrigger(hour=21, minute=15, timezone=ZoneInfo(settings.app_timezone)),
        id="scheduled_daily_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_weekly_recovery_backfill,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=10, timezone=ZoneInfo(settings.app_timezone)),
        id="scheduled_weekly_recovery_backfill",
        replace_existing=True,
    )
    scheduler.start()


async def run_startup_bootstrap() -> None:
    expected_provider = settings.database_provider.lower()
    database_required = expected_provider in {"postgres", "supabase"}
    retry_delay_seconds = max(min(settings.db_connect_timeout_seconds, 12), 4)
    database_warning_logged = False

    while True:
        database_ready = await asyncio.to_thread(refresh_database_status)
        if not database_required or database_ready:
            startup_steps = [
                ("admin-bootstrap", ensure_admin_user),
                ("default-schedules", db_service.ensure_default_schedules),
                ("data-retention", monitoring_service.enforce_data_retention),
            ]
            for component, callback in startup_steps:
                try:
                    await asyncio.to_thread(callback)
                except Exception as exc:
                    register_startup_issue(component, f"{component} fallo durante el arranque.", exc)
                    log_event(
                        logger,
                        level=40,
                        event="startup_step_failed",
                        component=component,
                        error=str(exc),
                    )

            try:
                monitoring_service.start_default_snapshot_warmup()
            except Exception as exc:
                register_startup_issue("snapshot-warmup", "El precalentamiento de snapshots fallo durante el arranque.", exc)
                log_event(
                    logger,
                    level=30,
                    event="startup_snapshot_warmup_failed",
                    error=str(exc),
                )
            mark_startup_phase("ready")
            return

        if not database_warning_logged:
            register_startup_issue(
                "database",
                "Supabase/Postgres no estuvo disponible durante el arranque. El servicio seguira en modo degradado.",
            )
            log_event(
                logger,
                level=40,
                event="startup_database_unavailable",
                provider=expected_provider,
                action="continue_in_degraded_mode",
            )
            database_warning_logged = True

        mark_database_status(False)
        mark_startup_phase("degraded")
        await asyncio.sleep(retry_delay_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(debug=settings.debug)
    reset_startup_issues()
    mark_startup_phase("starting")

    expected_provider = settings.database_provider.lower()
    if expected_provider not in {"mock", "supabase", "postgres"}:
        raise RuntimeError("DATABASE_PROVIDER must be one of: mock, supabase, postgres.")

    if expected_provider == "mock":
        mark_database_status(True)

    try:
        configure_internal_scheduler()
    except Exception as exc:
        register_startup_issue("scheduler", "El scheduler interno no pudo inicializarse.", exc)
        log_event(
            logger,
            level=40,
            event="startup_scheduler_failed",
            error=str(exc),
        )

    startup_task = None
    if expected_provider == "mock":
        await run_startup_bootstrap()
    else:
        startup_task = asyncio.create_task(run_startup_bootstrap())
    app.state.startup_task = startup_task
    yield
    if startup_task and not startup_task.done():
        startup_task.cancel()
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Animalitos Monitoring Platform",
    description="Real-time monitoring and analytics for Animalitos lotteries",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex_value,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/health", tags=["Health"])
async def health_check(response: Response):
    runtime_status = runtime_status_snapshot()
    if runtime_status.get("starting"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "starting",
            "database_connected": runtime_status["database_connected"],
            "database_provider": settings.database_provider.lower(),
            "scheduler_running": scheduler.running,
            "scheduler_mode": "external" if settings.use_external_scheduler else "internal",
            "scheduler_stale": None,
            "scheduler_last_received_at": None,
            "scheduler_last_completed_at": None,
            "scheduler_last_status": "starting",
            "scheduler_last_kind": None,
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "latest_successful_run_at": None,
            "latest_backfill_at": None,
            "total_results": 0,
            "warnings": [issue["message"] for issue in runtime_status["startup_issues"]],
            "startup_issues": runtime_status["startup_issues"],
            "timestamp": utc_now(),
        }
    if runtime_status["degraded"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "database_connected": runtime_status["database_connected"],
            "database_provider": settings.database_provider.lower(),
            "scheduler_running": scheduler.running,
            "scheduler_mode": "external" if settings.use_external_scheduler else "internal",
            "scheduler_stale": None,
            "scheduler_last_received_at": None,
            "scheduler_last_completed_at": None,
            "scheduler_last_status": "degraded",
            "scheduler_last_kind": None,
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "latest_successful_run_at": None,
            "latest_backfill_at": None,
            "total_results": 0,
            "warnings": [issue["message"] for issue in runtime_status["startup_issues"]],
            "startup_issues": runtime_status["startup_issues"],
            "timestamp": utc_now(),
        }

    status_report = await asyncio.to_thread(
        analytics_service.build_system_status,
        scheduler_running=scheduler.running,
    )
    return {
        "status": "healthy",
        "database_connected": status_report.database_connected,
        "database_provider": status_report.database_provider,
        "scheduler_running": status_report.scheduler_running,
        "scheduler_mode": status_report.scheduler_mode,
        "scheduler_stale": status_report.scheduler_stale,
        "scheduler_last_received_at": status_report.scheduler_last_received_at,
        "scheduler_last_completed_at": status_report.scheduler_last_completed_at,
        "scheduler_last_status": status_report.scheduler_last_status,
        "scheduler_last_kind": status_report.scheduler_last_kind,
        "telegram_configured": status_report.telegram_configured,
        "latest_successful_run_at": status_report.latest_successful_run.completed_at if status_report.latest_successful_run else None,
        "latest_backfill_at": status_report.latest_backfill_run.completed_at if status_report.latest_backfill_run else None,
        "total_results": status_report.total_results,
        "warnings": status_report.warnings,
        "startup_issues": runtime_status["startup_issues"],
        "timestamp": utc_now(),
    }


@app.get("/ping", tags=["Health"])
async def ping():
    runtime_status = runtime_status_snapshot()
    status_value = "starting" if runtime_status.get("starting") else ("degraded" if runtime_status["degraded"] else "ok")
    return {
        "status": status_value,
        "starting": runtime_status.get("starting", False),
        "degraded": runtime_status["degraded"],
        "startup_issues": runtime_status["startup_issues"],
        "timestamp": utc_now(),
    }


@app.get("/", tags=["Root"])
async def root():
    runtime_status = runtime_status_snapshot()
    return {
        "name": "Animalitos Monitoring Platform",
        "version": "2.0.0",
        "description": "Live monitoring, schedules, history, and analytics",
        "docs": "/docs",
        "health": "/health",
        "degraded": runtime_status["degraded"],
    }


try:
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
    if os.path.exists(frontend_path):
        app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
except Exception as exc:
    print(f"Frontend mount skipped: {exc}")
