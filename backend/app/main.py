import os
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.api import admin, auth, monitoring
from app.core.config import settings
from app.core.logging import configure_logging, get_logger, log_event
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


async def scheduled_weekly_recovery_backfill() -> None:
    await monitoring_service.run_weekly_recovery_backfill()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(debug=settings.debug)

    expected_provider = settings.database_provider.lower()
    if expected_provider in {"postgres", "supabase"} and not db_service.is_postgres_mode:
        raise RuntimeError("DATABASE_PROVIDER is set to postgres, but Postgres/Supabase is not reachable.")
    if expected_provider == "firebase" and not db_service.is_firestore_mode:
        raise RuntimeError("DATABASE_PROVIDER is set to firebase, but Firestore is not reachable.")

    ensure_admin_user()
    db_service.ensure_default_schedules()

    scheduler.add_job(
        scheduled_refresh,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="scheduled_refresh",
        replace_existing=True,
    )
    if not settings.use_external_scheduler:
        scheduler.add_job(
            scheduled_possible_results,
            trigger=CronTrigger(hour=8, minute=5, timezone=ZoneInfo(settings.app_timezone)),
            id="scheduled_possible_results",
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
    yield
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/health", tags=["Health"])
async def health_check():
    status_report = analytics_service.build_system_status(
        scheduler_running=scheduler.running
    )
    return {
        "status": "healthy",
        "firebase_connected": status_report.firebase_connected,
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
        "timestamp": utc_now(),
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "Animalitos Monitoring Platform",
        "version": "2.0.0",
        "description": "Live monitoring, schedules, history, and analytics",
        "docs": "/docs",
        "health": "/health",
    }


try:
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
    if os.path.exists(frontend_path):
        app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
except Exception as exc:
    print(f"Frontend mount skipped: {exc}")
