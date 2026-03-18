from datetime import date, datetime, timedelta, timezone

import pytest
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
