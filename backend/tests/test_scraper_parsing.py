from datetime import date, datetime, timezone

import pytest
from app.services.scraper import scraper_service


def test_parse_animalitos_fixture(fixtures_dir):
    html = (fixtures_dir / "animalitos_day.html").read_text(encoding="utf-8")

    results = scraper_service.parse_results_html(
        html_content=html,
        target_date=date(2026, 3, 17),
        source_page="animalitos",
        source_url="https://loteriadehoy.com/animalitos/resultados/2026-03-17/",
    )

    assert len(results) == 3
    assert results[0]["canonical_lottery_name"] == "Lotto Activo"
    assert results[0]["animal_number"] == 33
    assert results[0]["draw_time_local"] == "08:00"
    assert results[-1]["canonical_lottery_name"] == "La Granjita"
    assert results[-1]["animal_name"] == "Alacran"


def test_parse_internacional_alias_fixture(fixtures_dir):
    html = (fixtures_dir / "internacional_day.html").read_text(encoding="utf-8")

    results = scraper_service.parse_results_html(
        html_content=html,
        target_date=date(2026, 3, 17),
        source_page="internacional",
        source_url="https://loteriadehoy.com/internacional/resultados/2026-03-17/",
    )

    assert len(results) == 2
    assert all(item["canonical_lottery_name"] == "Lotto Activo Internacional" for item in results)
    assert results[0]["animal_number"] == 7
    assert results[1]["draw_time_local"] == "21:00"


def test_parse_empty_fixture_returns_no_results(fixtures_dir):
    html = (fixtures_dir / "no_results_day.html").read_text(encoding="utf-8")

    results = scraper_service.parse_results_html(
        html_content=html,
        target_date=date(2026, 3, 18),
        source_page="animalitos",
        source_url="https://loteriadehoy.com/animalitos/resultados/",
    )

    assert results == []


@pytest.mark.asyncio
async def test_fetch_results_for_date_retries_today_when_page_is_incomplete(monkeypatch):
    target_date = date(2026, 3, 20)

    class DummyResponse:
        def __init__(self, text: str = "<html></html>", status_code: int = 200):
            self.text = text
            self.status_code = status_code

        def raise_for_status(self):
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return DummyResponse(text=url)

    async def fake_sleep(_seconds):
        return None

    def fake_parse_results_html(html_content, target_date, source_page, source_url):
        if source_page != "animalitos":
            return []
        if "_rt=" in source_url:
            return [
                {
                    "canonical_lottery_name": "Lotto Activo",
                    "source_lottery_name": "Lotto Activo",
                    "draw_date": target_date,
                    "draw_time_local": "08:00",
                    "draw_datetime_utc": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                    "animal_number": 11,
                    "animal_name": "Gato",
                    "source_url": source_url,
                    "status": "confirmed",
                    "dedupe_key": f"lotto-activo:{target_date.isoformat()}:08:00:11",
                    "ingested_at": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                    "source_page": source_page,
                },
                {
                    "canonical_lottery_name": "La Granjita",
                    "source_lottery_name": "La Granjita",
                    "draw_date": target_date,
                    "draw_time_local": "08:00",
                    "draw_datetime_utc": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                    "animal_number": 12,
                    "animal_name": "Caballo",
                    "source_url": source_url,
                    "status": "confirmed",
                    "dedupe_key": f"la-granjita:{target_date.isoformat()}:08:00:12",
                    "ingested_at": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                    "source_page": source_page,
                },
            ]
        return [
            {
                "canonical_lottery_name": "Lotto Activo",
                "source_lottery_name": "Lotto Activo",
                "draw_date": target_date,
                "draw_time_local": "08:00",
                "draw_datetime_utc": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                "animal_number": 11,
                "animal_name": "Gato",
                "source_url": source_url,
                "status": "confirmed",
                "dedupe_key": f"lotto-activo:{target_date.isoformat()}:08:00:11",
                "ingested_at": datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
                "source_page": source_page,
            }
        ]

    monkeypatch.setattr("app.services.scraper.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("app.services.scraper.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(scraper_service, "parse_results_html", fake_parse_results_html)
    monkeypatch.setattr(scraper_service, "_expected_results_by_page", lambda target_date: {"animalitos": 2})

    payload = await scraper_service.fetch_results_for_date(target_date, include_today_urls=True)

    assert len(payload["results"]) == 2
    assert any("_rt=" in url for url in payload["source_urls"])
