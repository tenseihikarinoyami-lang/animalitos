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


def test_ensure_champion_models_can_skip_training(monkeypatch):
    monkeypatch.setattr("app.services.analytics.db_service.get_champion_model", lambda _segment_key: None)

    def fail_training(*_args, **_kwargs):
        raise AssertionError("training should not run on a lightweight request path")

    monkeypatch.setattr(analytics_service, "train_models_and_promote", fail_training)

    result = analytics_service.ensure_champion_models(train_if_missing=False)

    assert result
    assert all(item["status"] == "missing" for item in result.values())


def test_today_review_replays_missing_prediction_windows(monkeypatch):
    draw_date = date(2026, 3, 23)
    results = [
        {
            "canonical_lottery_name": "Lotto Activo",
            "draw_date": draw_date,
            "draw_time_local": "08:00",
            "draw_datetime_utc": datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
            "animal_number": 12,
            "animal_name": "Caballo",
        },
        {
            "canonical_lottery_name": "Lotto Activo",
            "draw_date": draw_date,
            "draw_time_local": "09:00",
            "draw_datetime_utc": datetime(2026, 3, 23, 13, 0, tzinfo=timezone.utc),
            "animal_number": 17,
            "animal_name": "Pavo",
        },
    ]
    persisted_reviews = []

    class FakeWindow:
        def __init__(self, draw_time_local: str, payload: dict):
            self.draw_time_local = draw_time_local
            self._payload = payload

        def model_dump(self):
            return self._payload

    monkeypatch.setattr(
        "app.services.analytics.db_service.get_results",
        lambda **_kwargs: results,
    )
    monkeypatch.setattr("app.services.analytics.db_service.get_prediction_runs", lambda limit=500: [])
    monkeypatch.setattr(
        "app.services.analytics.db_service.get_schedules",
        lambda: [{"canonical_lottery_name": "Lotto Activo", "times": ["08:00", "09:00"]}],
    )
    monkeypatch.setattr(
        "app.services.analytics.db_service.save_prediction_window_reviews",
        lambda rows: persisted_reviews.extend(rows),
    )
    monkeypatch.setattr(
        analytics_service,
        "_build_candidates_for_reference",
        lambda **_kwargs: SimpleNamespace(
            draw_predictions=[
                FakeWindow(
                    "09:00",
                    {
                        "draw_time_local": "09:00",
                        "segment_key": "lotto-activo-hourly",
                        "confidence_band": "media",
                        "stability_score": 0.72,
                        "candidates": [
                            {
                                "animal_number": 22,
                                "animal_name": "Camello",
                                "confidence_band": "media",
                                "stability_score": 0.72,
                                "segment_key": "lotto-activo-hourly",
                                "champion_model_key": "segment-model-1",
                                "strongest_signals": [{"key": "strategy_consensus", "label": "Consenso"}],
                            },
                            {
                                "animal_number": 17,
                                "animal_name": "Pavo",
                                "confidence_band": "media",
                                "stability_score": 0.72,
                                "segment_key": "lotto-activo-hourly",
                                "champion_model_key": "segment-model-1",
                                "strongest_signals": [{"key": "overdue_gap", "label": "Rezago"}],
                            },
                        ],
                    },
                )
            ]
        ),
    )

    review = analytics_service.build_today_prediction_review(draw_date=draw_date)

    assert review.evaluated_draws == 1
    assert review.hit_top_3 == 1
    assert any(window.prediction_delivery_status == "replay" for window in review.windows if window.prediction_available)
    assert persisted_reviews
    assert persisted_reviews[0]["canonical_lottery_name"] == "Lotto Activo"
