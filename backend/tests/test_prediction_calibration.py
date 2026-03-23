from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.models.schemas import StrategyPerformance
from app.services.analytics import analytics_service


def _observed_result(lottery_name: str, draw_time_local: str, animal_number: int) -> dict:
    return {
        "canonical_lottery_name": lottery_name,
        "draw_time_local": draw_time_local,
        "animal_number": animal_number,
        "animal_name": "Animal",
    }


def test_live_strategy_performance_prioritizes_guiding_strategy():
    observed_results = [
        _observed_result("Lotto Activo", "08:00", 17),
        _observed_result("Lotto Activo", "09:00", 17),
        _observed_result("Lotto Activo", "10:00", 4),
        _observed_result("La Granjita", "08:00", 3),
        _observed_result("La Granjita", "09:00", 10),
        _observed_result("Lotto Activo Internacional", "08:00", 22),
    ]
    strategies = [
        {
            "key": "alpha",
            "title": "Alpha",
            "animals": [{"animal_number": 17}, {"animal_number": 4}, {"animal_number": 30}],
        },
        {
            "key": "beta",
            "title": "Beta",
            "animals": [{"animal_number": 3}, {"animal_number": 12}],
        },
        {
            "key": "gamma",
            "title": "Gamma",
            "animals": [{"animal_number": 1}, {"animal_number": 2}],
        },
    ]
    system_top5 = {
        "Lotto Activo": [17, 4, 30, 31, 32],
        "La Granjita": [3, 10, 12, 19, 35],
    }

    rows = analytics_service._build_live_strategy_performance(
        observed_results=observed_results,
        strategies=strategies,
        system_top5_by_lottery=system_top5,
    )

    assert rows[0].key == "alpha"
    assert rows[0].is_guiding_strategy is True
    assert rows[0].strongest_lottery_name == "Lotto Activo"
    assert rows[0].strongest_lottery_hit_count == 3
    assert rows[0].guidance_score > rows[1].guidance_score > rows[2].guidance_score
    assert any(item["canonical_lottery_name"] == "Lotto Activo" for item in rows[0].by_lottery)


def test_summary_operating_mode_turns_conservative_when_windows_are_tight():
    candidate_a = SimpleNamespace(ensemble_score=0.57, score=0.57)
    candidate_b = SimpleNamespace(ensemble_score=0.55, score=0.55)
    candidate_c = SimpleNamespace(ensemble_score=0.535, score=0.535)
    window = SimpleNamespace(
        candidates=[candidate_a, candidate_b, candidate_c],
        weak_sample=False,
        confidence_band="media",
    )
    lottery = SimpleNamespace(draw_predictions=[window])
    summary = SimpleNamespace(
        prediction_stability={
            "high_confidence_windows": 0,
            "medium_confidence_windows": 3,
            "low_confidence_windows": 0,
            "average_stability_score": 0.58,
        },
        lotteries=[lottery, lottery, lottery],
    )

    operating_mode, notes = analytics_service._derive_summary_operating_mode(summary)

    assert operating_mode == "conservative"
    assert notes


def test_today_operating_mode_turns_conservative_when_replay_is_weak():
    review_summary = SimpleNamespace(evaluated_draws=10, hit_top_5_rate=0.1)
    strategies = [
        StrategyPerformance(
            key="alpha",
            title="Alpha",
            hit_count_today=2,
            evaluated_results_today=10,
            hit_rate_today=0.2,
            guidance_score=0.18,
        )
    ]

    operating_mode, notes = analytics_service._derive_today_operating_mode(
        review_summary=review_summary,
        strategy_performance=strategies,
        day_regime="mixto",
    )

    assert operating_mode == "conservative"
    assert notes


def test_today_operating_mode_can_turn_aggressive_when_everything_aligns():
    review_summary = SimpleNamespace(evaluated_draws=12, hit_top_5_rate=0.33)
    strategies = [
        StrategyPerformance(
            key="alpha",
            title="Alpha",
            hit_count_today=4,
            evaluated_results_today=12,
            hit_rate_today=0.25,
            guidance_score=0.42,
        )
    ]

    operating_mode, notes = analytics_service._derive_today_operating_mode(
        review_summary=review_summary,
        strategy_performance=strategies,
        day_regime="estable",
    )

    assert operating_mode == "aggressive"
    assert notes
