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
