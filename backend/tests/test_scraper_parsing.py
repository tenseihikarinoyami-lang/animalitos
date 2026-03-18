from datetime import date

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
