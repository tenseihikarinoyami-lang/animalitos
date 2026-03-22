import asyncio
import html
import logging
import re

import httpx

from app.core.config import settings
from app.core.logging import log_event


class TelegramService:
    MAX_MESSAGE_LENGTH = 4000

    def __init__(self) -> None:
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    @property
    def configured(self) -> bool:
        return bool(
            self.bot_token
            and self.chat_id
            and self.bot_token != "your_telegram_bot_token_here"
        )

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    @classmethod
    def _truncate_message(cls, message: str) -> str:
        if len(message) <= cls.MAX_MESSAGE_LENGTH:
            return message
        suffix = "\n\n[Mensaje truncado por longitud]"
        return message[: cls.MAX_MESSAGE_LENGTH - len(suffix)] + suffix

    @staticmethod
    def _plain_text_message(message: str) -> str:
        no_tags = re.sub(r"<[^>]+>", "", message)
        return html.unescape(no_tags)

    async def _post_message(self, message: str, parse_mode: str | None) -> httpx.Response:
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, http2=False) as client:
            return await client.post(
                f"{self.base_url}/sendMessage",
                json=payload,
            )

    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        if not self.configured:
            return False

        variants = [(self._truncate_message(message), parse_mode)]
        if parse_mode.upper() == "HTML":
            variants.append((self._truncate_message(self._plain_text_message(message)), None))

        last_error = None
        for index, (candidate_message, candidate_mode) in enumerate(variants):
            for attempt in range(1, 4):
                try:
                    response = await self._post_message(candidate_message, candidate_mode)
                    if response.status_code >= 400:
                        try:
                            last_error = response.json()
                        except Exception:
                            last_error = response.text
                        if candidate_mode and response.status_code in {400, 413, 422}:
                            break
                        response.raise_for_status()
                    payload = response.json()
                    if payload.get("ok", False):
                        log_event(
                            logging.getLogger(__name__),
                            logging.INFO,
                            "telegram_message_sent",
                            chat_id=self.chat_id,
                            parse_mode=candidate_mode or "plain",
                            attempt=attempt,
                            fallback=index > 0,
                        )
                        return True
                    last_error = payload
                except Exception as exc:
                    last_error = str(exc)

                await asyncio.sleep(min(attempt, 2))

        log_event(
            logging.getLogger(__name__),
            logging.ERROR,
            "telegram_send_error",
            error=str(last_error),
            chat_id=self.chat_id,
        )
        return False

    async def send_results_digest(self, results: list[dict], ingestion_run: dict) -> bool:
        if not results:
            return False

        preview = []
        for result in results[:8]:
            preview.append(
                f"- <b>{html.escape(result['canonical_lottery_name'])}</b> "
                f"{result['draw_time_local']} -> {result['animal_number']:02d} {html.escape(result['animal_name'])}"
            )

        message = "\n".join(
            [
                "<b>Animalitos Monitor</b>",
                "Nuevos resultados confirmados.",
                "",
                *preview,
                "",
                f"Nuevos: {ingestion_run['new_results']} | Duplicados: {ingestion_run['duplicates']}",
                f"Estado: {ingestion_run['status']}",
            ]
        )
        return await self.send_message(message)

    async def send_ingestion_alert(self, ingestion_run: dict) -> bool:
        message = "\n".join(
            [
                "<b>Animalitos Monitor</b>",
                "Alerta de ingesta.",
                "",
                f"Trigger: {html.escape(ingestion_run['trigger'])}",
                f"Estado: <b>{html.escape(ingestion_run['status'])}</b>",
                f"Errores: {len(ingestion_run.get('errors', []))}",
                f"Resultados encontrados: {ingestion_run.get('results_found', 0)}",
                "",
                *[f"- {html.escape(error)}" for error in ingestion_run.get("errors", [])[:5]],
            ]
        )
        return await self.send_message(message)

    async def send_daily_summary(self, overview: dict, review_summary: dict | None = None) -> bool:
        cards = overview.get("primary_lotteries", [])
        lines = [
            "<b>Animalitos Monitor</b>",
            "Resumen diario del tablero.",
            "",
            f"Resultados hoy: {overview.get('total_results_today', 0)}",
            f"Faltantes estimados: {overview.get('missing_draws_today', 0)}",
            "",
        ]

        for card in cards:
            lines.append(
                f"- <b>{html.escape(card['canonical_lottery_name'])}</b>: "
                f"{card['total_results_today']}/{card['expected_results_today']}"
            )

        if review_summary:
            lines.extend(
                [
                    "",
                    "<b>Revision de prediccion</b>",
                    (
                        f"Top 1: {round(review_summary.get('hit_top_1_rate', 0) * 100, 1)}% | "
                        f"Top 3: {round(review_summary.get('hit_top_3_rate', 0) * 100, 1)}% | "
                        f"Top 5: {round(review_summary.get('hit_top_5_rate', 0) * 100, 1)}%"
                    ),
                ]
            )
            for lottery in review_summary.get("by_lottery", [])[:3]:
                lines.append(
                    f"- <b>{html.escape(lottery['canonical_lottery_name'])}</b>: "
                    f"Top 5 {lottery.get('hit_top_5', 0)}/{lottery.get('evaluated_draws', 0)}"
                )

            strongest_signal = (review_summary.get("strongest_signals") or [None])[0]
            weakest_signal = (review_summary.get("weakest_signals") or [None])[0]
            if strongest_signal:
                lines.append(
                    f"Mejor senal lider: {html.escape(strongest_signal['signal_label'])} "
                    f"({round(strongest_signal.get('hit_top_3_rate', 0) * 100, 1)}% top 3)"
                )
            if weakest_signal:
                lines.append(
                    f"Senal mas floja: {html.escape(weakest_signal['signal_label'])} "
                    f"({round(weakest_signal.get('hit_top_3_rate', 0) * 100, 1)}% top 3)"
                )

        return await self.send_message("\n".join(lines))

    async def send_possible_results_summary(self, summary: dict) -> bool:
        lotteries = summary.get("lotteries", [])
        if not lotteries:
            return False

        lines = [
            "<b>Animalitos Monitor</b>",
            "Posibles resultados de hoy segun tendencia estadistica.",
            "",
            (
                f"Base: {html.escape(summary.get('methodology_version', 'sin-version'))} | "
                f"referencia {html.escape(str(summary.get('reference_time_local') or '--:--'))}."
            ),
            "",
        ]

        change_alerts = summary.get("change_alerts", [])
        if change_alerts:
            lines.append("<b>Cambios relevantes</b>")
            lines.extend(f"- {html.escape(alert)}" for alert in change_alerts[:4])
            lines.append("")

        for lottery in lotteries[:3]:
            lines.append(f"<b>{html.escape(lottery['canonical_lottery_name'])}</b>")
            next_draw = lottery.get("next_draw_time_local") or "Sin sorteo pendiente"
            lines.append(
                f"Proximo: {html.escape(next_draw)} | Pendientes hoy: {lottery.get('remaining_draws_today', 0)}"
            )
            next_window = (lottery.get("draw_predictions") or [{}])[0]
            candidates = next_window.get("candidates") or lottery.get("candidates", [])
            for candidate in candidates[:5]:
                strongest_signal = max((candidate.get("score_breakdown") or {}).items(), key=lambda item: item[1], default=("n/a", 0))
                lines.append(
                    f"- {candidate['animal_number']:02d} {html.escape(candidate['animal_name'])} | "
                    f"score {candidate['score']:.2f} | slot {candidate.get('slot_hits', candidate.get('remaining_time_hits', 0))} | "
                    f"coinc {candidate.get('coincidence_hits', 0)} | trans {candidate.get('transition_hits', 0)} | "
                    f"senal {html.escape(strongest_signal[0])}"
                )
            lines.append("")

        lines.append("Nota: reporte estadistico, no garantiza aciertos.")
        return await self.send_message("\n".join(lines))

    async def send_pre_draw_alerts(self, alerts: list[dict]) -> bool:
        if not alerts:
            return False

        lines = [
            "<b>Animalitos Monitor</b>",
            "Alerta previa al siguiente sorteo.",
            "",
        ]
        for alert in alerts[:4]:
            lines.append(
                f"<b>{html.escape(alert['lottery_name'])}</b> | sorteo {html.escape(alert['draw_time_local'])} "
                f"en {alert['minutes_until']} min"
            )
            for candidate in alert.get("candidates", [])[:3]:
                lines.append(
                    f"- {candidate['animal_number']:02d} {html.escape(candidate['animal_name'])} | "
                    f"score {candidate['score']:.2f} | top delta {candidate.get('rank_delta') or 0}"
                )
            if alert.get("change_summary"):
                lines.append(f"  Cambio: {html.escape(alert['change_summary'])}")
            lines.append("")

        lines.append("Nota: alerta operativa basada en ranking estadistico.")
        return await self.send_message("\n".join(lines))

    async def test_connection(self) -> dict:
        if not self.configured:
            return {"success": False, "message": "Telegram is not configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/getMe")
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    return {"success": False, "message": "Telegram API returned an error"}
                result = data.get("result", {})
                return {
                    "success": True,
                    "message": f"Connected to @{result.get('username', 'unknown')}",
                    "bot_name": result.get("first_name", "Unknown"),
                }
        except Exception as exc:
            return {"success": False, "message": str(exc)}


telegram_service = TelegramService()
