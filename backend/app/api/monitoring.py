from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.auth import get_current_user
from app.core.config import settings
from app.models.schemas import (
    AnalyticsTrends,
    BacktestingSummary,
    DashboardOverview,
    EnjauladosResponse,
    PossibleResultsSummary,
    PredictionReviewSummary,
    ResultQueryResponse,
    ScheduleEntry,
    StrategiesResponse,
)
from app.services.analytics import analytics_service
from app.services.database import db_service
from app.services.monitoring import monitoring_service
from app.services.schedule import local_now


router = APIRouter(tags=["Monitoring"])


def require_scheduler_token(x_scheduler_token: str | None = Header(default=None)) -> None:
    if not settings.scheduler_service_token or x_scheduler_token != settings.scheduler_service_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid scheduler token")


def _default_snapshot(snapshot_prefix: str) -> dict | None:
    today_key = local_now().date().isoformat()
    return db_service.get_analytics_snapshot(f"{snapshot_prefix}{today_key}") or db_service.get_latest_analytics_snapshot(
        snapshot_prefix=snapshot_prefix
    )


def _default_trends_request(lottery_name: str | None, days: int | None) -> bool:
    return not lottery_name and days in {None, settings.analytics_default_days}


def _default_possible_results_request(top_n: int | None, lotteries: str | None) -> bool:
    return not lotteries and top_n in {None, settings.prediction_default_top_n}


def _default_backtesting_request(days: int | None, top_n: int | None, lotteries: str | None) -> bool:
    return (
        not lotteries
        and days in {None, settings.analytics_default_days}
        and top_n in {None, settings.prediction_default_top_n}
    )


@router.get("/dashboard/overview", response_model=DashboardOverview)
async def get_dashboard_overview(current_user: dict = Depends(get_current_user)):
    snapshot = _default_snapshot("overview:")
    monitoring_service.schedule_recovery_check(trigger="dashboard")
    if snapshot:
        return snapshot
    return analytics_service.build_dashboard_overview()


@router.get("/results", response_model=ResultQueryResponse)
async def get_results(
    lottery_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    draw_time_local: str | None = None,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    items = db_service.get_results(
        canonical_lottery_name=lottery_name,
        start_date=start_date,
        end_date=end_date,
        draw_time_local=draw_time_local,
        limit=limit,
    )
    return {
        "items": items,
        "total": len(items),
        "filters": {
            "lottery_name": lottery_name,
            "start_date": start_date,
            "end_date": end_date,
            "draw_time_local": draw_time_local,
            "limit": limit,
        },
    }


@router.get("/results/today", response_model=ResultQueryResponse)
async def get_today_results(
    lottery_name: str | None = None,
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    monitoring_service.schedule_recovery_check(trigger="today-results")
    today = local_now().date().isoformat()
    items = db_service.get_results(
        canonical_lottery_name=lottery_name,
        start_date=today,
        end_date=today,
        limit=limit,
    )
    return {
        "items": items,
        "total": len(items),
        "filters": {"lottery_name": lottery_name, "date": today, "limit": limit},
    }


@router.get("/results/history", response_model=ResultQueryResponse)
async def get_results_history(
    lottery_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    draw_time_local: str | None = None,
    limit: int = 500,
    current_user: dict = Depends(get_current_user),
):
    items = db_service.get_results(
        canonical_lottery_name=lottery_name,
        start_date=start_date,
        end_date=end_date,
        draw_time_local=draw_time_local,
        limit=limit,
    )
    return {
        "items": items,
        "total": len(items),
        "filters": {
            "lottery_name": lottery_name,
            "start_date": start_date,
            "end_date": end_date,
            "draw_time_local": draw_time_local,
            "limit": limit,
        },
    }


@router.get("/schedules", response_model=list[ScheduleEntry])
async def get_schedules(current_user: dict = Depends(get_current_user)):
    return db_service.get_schedules()


@router.get("/analytics/trends", response_model=AnalyticsTrends)
async def get_trends(
    lottery_name: str | None = None,
    days: int | None = None,
    current_user: dict = Depends(get_current_user),
):
    if _default_trends_request(lottery_name, days):
        snapshot = _default_snapshot("trends:default:")
        if snapshot:
            return snapshot

    try:
        return analytics_service.build_trends(lottery_name=lottery_name, days=days)
    except Exception:
        snapshot = _default_snapshot("trends:default:")
        if snapshot:
            return snapshot
        raise


@router.get("/analytics/possible-results", response_model=PossibleResultsSummary)
async def get_possible_results(
    top_n: int | None = None,
    lotteries: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    if _default_possible_results_request(top_n, lotteries):
        snapshot = _default_snapshot("possible-results:default:")
        if snapshot:
            return snapshot

    selected_lotteries = [item.strip() for item in lotteries.split(",")] if lotteries else None
    try:
        return analytics_service.build_possible_results_summary(top_n=top_n, lotteries=selected_lotteries)
    except Exception:
        snapshot = _default_snapshot("possible-results:default:")
        if snapshot:
            return snapshot
        raise


@router.get("/analytics/backtesting", response_model=BacktestingSummary)
async def get_backtesting(
    days: int | None = None,
    top_n: int | None = None,
    lotteries: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    if _default_backtesting_request(days, top_n, lotteries):
        snapshot = _default_snapshot("backtesting:default:")
        if snapshot:
            return snapshot
        monitoring_service.start_backtesting_snapshot_refresh()
        return analytics_service.build_backtesting_placeholder_summary(days=days)

    selected_lotteries = [item.strip() for item in lotteries.split(",")] if lotteries else None
    try:
        return analytics_service.build_backtesting_summary(days=days, top_n=top_n, lotteries=selected_lotteries)
    except Exception:
        snapshot = _default_snapshot("backtesting:default:")
        if snapshot:
            return snapshot
        raise


@router.get("/analytics/enjaulados", response_model=EnjauladosResponse)
async def get_enjaulados(
    force_refresh: bool = False,
    current_user: dict = Depends(get_current_user),
):
    return analytics_service.build_enjaulados_summary(force_refresh=force_refresh)


@router.get("/analytics/strategies", response_model=StrategiesResponse)
async def get_strategies(
    force_refresh: bool = False,
    current_user: dict = Depends(get_current_user),
):
    return analytics_service.build_strategies_summary(force_refresh=force_refresh)


@router.get("/analytics/today-review", response_model=PredictionReviewSummary)
async def get_today_review(
    draw_date: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    return analytics_service.build_today_prediction_review(
        draw_date=None if not draw_date else date.fromisoformat(draw_date)
    )


@router.post("/internal/scheduler/refresh")
async def internal_scheduler_refresh(_: None = Depends(require_scheduler_token)):
    refresh_status, started = await monitoring_service.start_scheduler_refresh(trigger="cloud-scheduler", notify=True)
    return {
        "accepted": started,
        "message": "Refresh programado en segundo plano." if started else "Ya habia un refresh del scheduler en ejecucion.",
        "details": refresh_status,
    }


@router.post("/internal/scheduler/possible-results")
async def internal_scheduler_possible_results(_: None = Depends(require_scheduler_token)):
    return await monitoring_service.send_today_possible_results(preview_only=False)


@router.post("/internal/scheduler/daily-summary")
async def internal_scheduler_daily_summary(_: None = Depends(require_scheduler_token)):
    return {"sent": await monitoring_service.send_daily_summary()}


@router.post("/internal/scheduler/weekly-backfill")
async def internal_scheduler_weekly_backfill(_: None = Depends(require_scheduler_token)):
    return await monitoring_service.run_weekly_recovery_backfill()
