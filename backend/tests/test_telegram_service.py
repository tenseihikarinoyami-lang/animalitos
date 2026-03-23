import pytest

from app.services.telegram import telegram_service


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_send_message_retries_plain_text_after_html_failure(monkeypatch):
    calls = []

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            calls.append(json)
            if len(calls) == 1:
                return _DummyResponse(400, {"ok": False, "description": "Bad Request"})
            return _DummyResponse(200, {"ok": True})

    original_bot_token = telegram_service.bot_token
    original_chat_id = telegram_service.chat_id
    try:
        telegram_service.bot_token = "test-token"
        telegram_service.chat_id = "123"
        monkeypatch.setattr("app.services.telegram.httpx.AsyncClient", DummyClient)

        sent = await telegram_service.send_message("<b>Hola</b>", parse_mode="HTML")

        assert sent is True
        assert calls[0]["parse_mode"] == "HTML"
        assert calls[0]["text"] == "<b>Hola</b>"
        assert "parse_mode" not in calls[-1]
        assert calls[-1]["text"] == "Hola"
    finally:
        telegram_service.bot_token = original_bot_token
        telegram_service.chat_id = original_chat_id


def test_plain_text_message_strips_html():
    assert telegram_service._plain_text_message("<b>Animalitos</b> &amp; mas") == "Animalitos & mas"


def test_is_conservative_window_detects_low_conviction():
    candidates = [
        {"animal_number": 1, "animal_name": "Carnero", "confidence_band": "media", "stability_score": 0.49, "ensemble_score": 0.57},
        {"animal_number": 2, "animal_name": "Toro", "confidence_band": "media", "stability_score": 0.49, "ensemble_score": 0.55},
        {"animal_number": 3, "animal_name": "Ciempies", "confidence_band": "media", "stability_score": 0.49, "ensemble_score": 0.535},
    ]

    assert telegram_service._is_conservative_window(candidates) is True


@pytest.mark.asyncio
async def test_send_possible_results_summary_limits_output_in_conservative_mode(monkeypatch):
    captured = {}

    async def fake_send_message(message, parse_mode="HTML"):
        captured["message"] = message
        captured["parse_mode"] = parse_mode
        return True

    monkeypatch.setattr(telegram_service, "send_message", fake_send_message)

    summary = {
        "methodology_version": "ops-hybrid-ranking-v10",
        "reference_time_local": "08:00",
        "operating_mode": "conservative",
        "prediction_stability": {
            "high_confidence_windows": 0,
            "medium_confidence_windows": 3,
            "low_confidence_windows": 0,
            "average_stability_score": 0.58,
        },
        "change_alerts": [],
        "lotteries": [
            {
                "canonical_lottery_name": "Lotto Activo",
                "next_draw_time_local": "09:00",
                "remaining_draws_today": 11,
                "draw_predictions": [
                    {
                        "stability_score": 0.55,
                        "candidates": [
                            {"animal_number": 1, "animal_name": "Carnero", "ensemble_score": 0.57, "model_probability": 0.32, "rule_score": 41.2, "confidence_band": "media", "score_breakdown": {"strategy_consensus": 0.18}},
                            {"animal_number": 2, "animal_name": "Toro", "ensemble_score": 0.55, "model_probability": 0.31, "rule_score": 40.3, "confidence_band": "media", "score_breakdown": {"strategy_adaptive": 0.16}},
                            {"animal_number": 3, "animal_name": "Ciempies", "ensemble_score": 0.535, "model_probability": 0.30, "rule_score": 39.8, "confidence_band": "media", "score_breakdown": {"enjaulado_pressure": 0.14}},
                            {"animal_number": 4, "animal_name": "Alacran", "ensemble_score": 0.52, "model_probability": 0.28, "rule_score": 38.1, "confidence_band": "media", "score_breakdown": {"slot_recent_14d": 0.11}},
                        ],
                    }
                ],
            }
        ],
    }

    sent = await telegram_service.send_possible_results_summary(summary)

    assert sent is True
    assert "Modo conservador del sistema" in captured["message"]
    assert "04 Alacran" not in captured["message"]
