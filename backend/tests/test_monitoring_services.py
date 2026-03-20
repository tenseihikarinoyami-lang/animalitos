from datetime import date, datetime, timedelta, timezone

import pytest
from app.core.config import settings
from app.models.schemas import BackfillRequest
from app.services.analytics import analytics_service
from app.services.database import db_service
from app.services.monitoring import monitoring_service
from app.services.schedule import local_now


def _sample_result(draw_date: date, draw_time_local: str, number: int, lottery_name: str):
    slug = lottery_name.lower().replace(" ", "-")
    return {
        "canonical_lottery_name": lottery_name,
        "source_lottery_name": lottery_name,
        "draw_date": draw_date,
        "draw_time_local": draw_time_local,
        "draw_datetime_utc": datetime.strptime(
            f"{draw_date.isoformat()}T{draw_time_local}:00+0000",
            "%Y-%m-%dT%H:%M:%S%z",
        ).astimezone(timezone.utc),
        "animal_number": number,
        "animal_name": "Animal",
        "source_url": "https://example.com",
        "status": "confirmed",
        "dedupe_key": f"{slug}:{draw_date.isoformat()}:{draw_time_local}:{number:02d}",
        "ingested_at": datetime(2026, 3, 18, tzinfo=timezone.utc),
        "source_page": "animalitos",
    }


def test_upsert_results_deduplicates_by_dedupe_key():
    result = _sample_result(date(2026, 3, 17), "08:00", 33, "Lotto Activo")

    first_insert = db_service.upsert_results([result])
    second_insert = db_service.upsert_results([result])

    assert first_insert["new_count"] == 1
    assert second_insert["new_count"] == 0
    assert second_insert["duplicate_count"] == 1


def test_explicit_postgres_failure_does_not_fallback_to_mock(monkeypatch):
    class BrokenEngine:
        def begin(self):
            raise RuntimeError("postgres-down")

    original_provider = settings.database_provider
    original_database_url = settings.database_url
    original_engine = db_service.pg_engine
    try:
        monkeypatch.setattr("app.services.database.postgres_initialized", True)
        settings.database_provider = "postgres"
        settings.database_url = "postgresql://example"
        db_service.pg_engine = BrokenEngine()

        with pytest.raises(RuntimeError, match="postgres-down"):
            db_service.get_schedules()

        assert db_service.pg_engine is not None
    finally:
        settings.database_provider = original_provider
        settings.database_url = original_database_url
        db_service.pg_engine = original_engine

    settings.database_provider = original_provider
    settings.database_url = original_database_url
    db_service.pg_engine = original_engine


@pytest.mark.asyncio
async def test_backfill_aggregates_results(monkeypatch):
    async def fake_fetch_results_for_date(target_date, include_today_urls=False):
        if target_date == date(2026, 3, 15):
            return {"results": [], "errors": [], "source_urls": ["https://example.com/empty"]}
        return {
            "results": [
                _sample_result(target_date, "08:00", 11, "Lotto Activo"),
                _sample_result(target_date, "09:00", 12, "La Granjita"),
            ],
            "errors": [],
            "source_urls": [f"https://example.com/{target_date.isoformat()}"],
        }

    monkeypatch.setattr(
        "app.services.monitoring.scraper_service.fetch_results_for_date",
        fake_fetch_results_for_date,
    )

    response = await monitoring_service.backfill(
        BackfillRequest(start_date=date(2026, 3, 15), end_date=date(2026, 3, 17))
    )

    assert response["details"]["new_results"] == 4
    assert response["details"]["empty_days"] == ["2026-03-15"]


@pytest.mark.asyncio
async def test_background_backfill_reports_status_and_finishes(monkeypatch):
    async def fake_fetch_results_for_date(target_date, include_today_urls=False):
        return {
            "results": [
                _sample_result(target_date, "08:00", 11, "Lotto Activo"),
            ],
            "errors": [],
            "source_urls": [f"https://example.com/{target_date.isoformat()}"],
            "source_reports": [],
        }

    monkeypatch.setattr(
        "app.services.monitoring.scraper_service.fetch_results_for_date",
        fake_fetch_results_for_date,
    )

    snapshot, started = await monitoring_service.start_backfill(
        BackfillRequest(start_date=date(2026, 3, 15), end_date=date(2026, 3, 16))
    )

    assert started is True
    assert snapshot["status"] == "queued"
    assert monitoring_service._backfill_task is not None

    await monitoring_service._backfill_task
    final_status = monitoring_service.get_backfill_status()

    assert final_status is not None
    assert final_status["status"] == "completed"
    assert final_status["completed_days"] == 2
    assert final_status["new_results"] == 2
    assert final_status["ingestion_run_id"]


def test_possible_results_summary_prioritizes_recent_and_frequent_animals():
    today = local_now().date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    seed = [
        _sample_result(today, "08:00", 12, "Lotto Activo"),
        _sample_result(today, "09:00", 12, "Lotto Activo"),
        _sample_result(today, "10:00", 12, "Lotto Activo"),
        _sample_result(today, "11:00", 25, "Lotto Activo"),
        _sample_result(yesterday, "08:00", 12, "Lotto Activo"),
        _sample_result(yesterday, "09:00", 25, "Lotto Activo"),
        _sample_result(two_days_ago, "08:00", 12, "Lotto Activo"),
        _sample_result(two_days_ago, "09:00", 33, "Lotto Activo"),
    ]
    db_service.upsert_results(seed)

    summary = analytics_service.build_possible_results_summary(top_n=3)
    lotto_activo = next(item for item in summary.lotteries if item.canonical_lottery_name == "Lotto Activo")

    assert lotto_activo.candidates
    assert lotto_activo.candidates[0].animal_number == 12
    assert lotto_activo.history_results_considered >= 8
    assert lotto_activo.top_10
    assert lotto_activo.draw_predictions[0].candidates[0].score_breakdown
    assert summary.baseline_methodology_version == analytics_service.BASELINE_METHODOLOGY_VERSION


def test_backtesting_summary_exposes_baseline_metrics():
    today = local_now().date()
    seed = []
    for day_offset, animal_number in enumerate([12, 12, 25, 12, 33, 12, 45, 12, 12, 7, 25, 12, 33, 12, 21]):
        seed.append(_sample_result(today - timedelta(days=day_offset), "08:00", animal_number, "Lotto Activo"))
    db_service.upsert_results(seed)

    summary = analytics_service.build_backtesting_summary(days=30)

    assert summary.baseline_methodology_version == analytics_service.BASELINE_METHODOLOGY_VERSION
    assert summary.by_lottery
    assert summary.by_lottery[0].baseline_top_3_rate >= 0
    assert isinstance(summary.beats_baseline, bool)


@pytest.mark.asyncio
async def test_pre_draw_alerts_send_once(monkeypatch):
    today = local_now().date()
    seed = [
        _sample_result(today, "08:00", 12, "Lotto Activo"),
        _sample_result(today, "09:00", 25, "Lotto Activo"),
        _sample_result(today - timedelta(days=1), "08:00", 12, "Lotto Activo"),
        _sample_result(today - timedelta(days=1), "09:00", 25, "Lotto Activo"),
        _sample_result(today - timedelta(days=2), "08:00", 12, "Lotto Activo"),
        _sample_result(today - timedelta(days=2), "09:00", 33, "Lotto Activo"),
    ]
    db_service.upsert_results(seed)

    sent_alerts = []

    async def fake_send(alerts):
        sent_alerts.append(alerts)
        return True

    monkeypatch.setattr("app.services.monitoring.telegram_service.send_pre_draw_alerts", fake_send)

    reference_local = local_now().replace(hour=9, minute=55, second=0, microsecond=0)
    summary = analytics_service.build_possible_results_summary(reference_local=reference_local)

    first = await monitoring_service.send_due_pre_draw_alerts(summary=summary)
    second = await monitoring_service.send_due_pre_draw_alerts(summary=summary)

    assert first["sent"] is True
    assert first["alerts"]
    assert second["sent"] is False
    assert len(sent_alerts) == 1
