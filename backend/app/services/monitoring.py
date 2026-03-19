import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.config import settings
from app.core.logging import log_event
from app.models.schemas import BackfillRequest
from app.services.analytics import analytics_service
from app.services.database import db_service
from app.services.schedule import local_now, utc_now
from app.services.scraper import scraper_service
from app.services.telegram import telegram_service


class MonitoringService:
    BACKFILL_STATUS_SNAPSHOT_KEY = "admin:backfill-status"
    BACKFILL_STALE_MINUTES = 20

    def __init__(self) -> None:
        self._backfill_task: asyncio.Task | None = None

    @staticmethod
    def _coerce_datetime(value) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return None

    def _save_backfill_snapshot(self, payload: dict) -> dict:
        snapshot = deepcopy(payload)
        snapshot["generated_at"] = snapshot.get("updated_at") or utc_now()
        db_service.save_analytics_snapshot(
            snapshot_key=self.BACKFILL_STATUS_SNAPSHOT_KEY,
            snapshot=snapshot,
        )
        snapshot.pop("generated_at", None)
        return snapshot

    def get_backfill_status(self) -> dict | None:
        snapshot = db_service.get_analytics_snapshot(self.BACKFILL_STATUS_SNAPSHOT_KEY)
        if not snapshot:
            return None

        snapshot = deepcopy(snapshot)
        snapshot.pop("generated_at", None)
        status = snapshot.get("status")
        updated_at = self._coerce_datetime(snapshot.get("updated_at"))
        task_active = bool(self._backfill_task and not self._backfill_task.done())

        if status in {"queued", "running", "finalizing"} and not task_active and updated_at:
            if utc_now() - updated_at > timedelta(minutes=self.BACKFILL_STALE_MINUTES):
                snapshot["status"] = "stale"
                snapshot["message"] = "El ultimo backfill se interrumpio antes de completarse."
                snapshot["updated_at"] = utc_now()
                snapshot["completed_at"] = snapshot.get("completed_at") or snapshot["updated_at"]
                snapshot = self._save_backfill_snapshot(snapshot)

        return snapshot

    def _resolve_backfill_range(self, request: BackfillRequest) -> tuple:
        now_local = local_now().date()
        days = request.days or settings.backfill_default_days
        end_date = request.end_date or now_local
        start_date = request.start_date or (end_date - timedelta(days=days - 1))
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        total_days = (end_date - start_date).days + 1
        return start_date, end_date, total_days

    def _create_backfill_snapshot(self, request: BackfillRequest, trigger: str) -> dict:
        start_date, end_date, total_days = self._resolve_backfill_range(request)
        now = utc_now()
        return {
            "job_id": str(uuid4()),
            "status": "queued",
            "trigger": f"{trigger}:backfill",
            "message": "Backfill en cola para ejecutarse en segundo plano.",
            "start_date": start_date,
            "end_date": end_date,
            "total_days": total_days,
            "completed_days": 0,
            "current_date": start_date,
            "results_found": 0,
            "new_results": 0,
            "duplicates": 0,
            "empty_days": [],
            "errors_count": 0,
            "last_error": None,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "ingestion_run_id": None,
        }

    async def start_backfill(self, request: BackfillRequest, trigger: str = "manual") -> tuple[dict, bool]:
        task_active = bool(self._backfill_task and not self._backfill_task.done())
        current = self.get_backfill_status()
        if task_active and current and current.get("status") in {"queued", "running", "finalizing"}:
            return current, False

        snapshot = self._create_backfill_snapshot(request, trigger)
        self._save_backfill_snapshot(snapshot)
        self._backfill_task = asyncio.create_task(
            self._run_backfill_job(
                request=request,
                trigger=trigger,
                snapshot=snapshot,
            )
        )
        return snapshot, True

    def _persist_default_snapshots(
        self,
        overview=None,
        trends=None,
        possible_results=None,
        backtesting=None,
    ) -> None:
        overview = overview or analytics_service.build_dashboard_overview()
        trends = trends or analytics_service.build_trends(days=settings.analytics_default_days)
        possible_results = possible_results or analytics_service.build_possible_results_summary()
        backtesting = backtesting or analytics_service.build_backtesting_summary(days=settings.analytics_default_days)

        today_key = local_now().date().isoformat()
        db_service.save_analytics_snapshot(snapshot_key=f"overview:{today_key}", snapshot=overview.model_dump())
        db_service.save_analytics_snapshot(
            snapshot_key=f"trends:default:{today_key}",
            snapshot=trends.model_dump(),
        )
        db_service.save_analytics_snapshot(
            snapshot_key=f"possible-results:default:{today_key}",
            snapshot=possible_results.model_dump(),
        )
        db_service.save_analytics_snapshot(
            snapshot_key=f"backtesting:default:{today_key}",
            snapshot=backtesting.model_dump(),
        )

    def _latest_prediction_summary(self) -> dict | None:
        latest_prediction = db_service.get_latest_prediction_run()
        return latest_prediction.get("summary") if latest_prediction else None

    def _recent_pre_draw_window_keys(self) -> set[str]:
        keys = set()
        for run in db_service.get_prediction_runs(limit=100):
            summary = run.get("summary", {})
            delivery_context = summary.get("delivery_context", {})
            if delivery_context.get("kind") != "pre-draw-alert":
                continue
            for window_key in delivery_context.get("alerted_window_keys", []):
                keys.add(window_key)
        return keys

    def _collect_pre_draw_alerts(self, summary) -> list[dict]:
        alerts = []
        seen_keys = self._recent_pre_draw_window_keys()
        reference_date = str(summary.reference_date or local_now().date())

        for lottery in summary.lotteries:
            next_window = lottery.draw_predictions[0] if lottery.draw_predictions else None
            if not next_window or next_window.minutes_until is None:
                continue
            if not (0 <= next_window.minutes_until <= settings.prediction_pre_draw_lead_minutes):
                continue

            window_key = f"{reference_date}:{lottery.canonical_lottery_name}:{next_window.draw_time_local}"
            if window_key in seen_keys:
                continue

            alerts.append(
                {
                    "window_key": window_key,
                    "lottery_name": lottery.canonical_lottery_name,
                    "draw_time_local": next_window.draw_time_local,
                    "minutes_until": next_window.minutes_until,
                    "change_summary": next_window.change_summary,
                    "candidates": [
                        {
                            "animal_number": candidate.animal_number,
                            "animal_name": candidate.animal_name,
                            "score": candidate.score,
                            "rank_delta": candidate.rank_delta,
                        }
                        for candidate in next_window.candidates[:3]
                    ],
                }
            )

        return alerts

    def _build_run_quality_metadata(
        self,
        start_date,
        end_date,
        source_reports: list[dict],
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        all_results = db_service.get_results(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            limit=None,
        )
        grouped = {}
        for result in all_results:
            key = (result["draw_date"], result["canonical_lottery_name"])
            grouped.setdefault(key, set()).add(result["draw_time_local"])

        source_report_map = {}
        for report in source_reports:
            key = (report.get("draw_date"), report.get("source_page"))
            source_report_map[key] = report.get("status")

        missing_slots = {}
        source_status = {}
        current_date = start_date
        while current_date <= end_date:
            date_key = current_date.isoformat()
            for lottery_name, schedule in schedules.items():
                found_times = grouped.get((date_key, lottery_name), set())
                missing = [time_value for time_value in schedule.get("times", []) if time_value not in found_times]
                missing_slots[f"{date_key}:{lottery_name}"] = missing
                source_page = (schedule.get("source_pages") or [None])[0]
                source_status[f"{date_key}:{lottery_name}"] = source_report_map.get((date_key, source_page), "unknown")
            current_date += timedelta(days=1)

        return missing_slots, source_status

    def _update_backfill_snapshot(self, snapshot: dict, **updates) -> dict:
        next_snapshot = deepcopy(snapshot)
        next_snapshot.update(updates)
        next_snapshot["updated_at"] = updates.get("updated_at") or utc_now()
        return self._save_backfill_snapshot(next_snapshot)

    async def refresh_today(self, trigger: str = "manual", notify: bool = True) -> dict:
        started_at = utc_now()
        today = local_now().date()
        scrape_payload = await scraper_service.fetch_today_results()
        save_stats = db_service.upsert_results(scrape_payload["results"])
        completed_at = utc_now()
        missing_slots, source_status = self._build_run_quality_metadata(
            start_date=today,
            end_date=today,
            source_reports=scrape_payload.get("source_reports", []),
        )

        status = "success"
        if scrape_payload["errors"] and save_stats["new_count"] == 0 and not scrape_payload["results"]:
            status = "failed"
        elif scrape_payload["errors"]:
            status = "partial"
        elif not scrape_payload["results"]:
            status = "empty"

        ingestion_run = {
            "trigger": trigger,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round((completed_at - started_at).total_seconds(), 2),
            "results_found": len(scrape_payload["results"]),
            "new_results": save_stats["new_count"],
            "duplicates": save_stats["duplicate_count"],
            "errors": scrape_payload["errors"],
            "source_urls": scrape_payload["source_urls"],
            "lotteries_seen": sorted({result["canonical_lottery_name"] for result in scrape_payload["results"]}),
            "coverage_start": today,
            "coverage_end": today,
            "parser_version": scrape_payload.get("parser_version"),
            "missing_slots": missing_slots,
            "source_status": source_status,
            "source_reports": scrape_payload.get("source_reports", []),
        }
        run_id = db_service.save_ingestion_run(ingestion_run)
        ingestion_run["id"] = run_id

        overview = analytics_service.build_dashboard_overview()
        trends = analytics_service.build_trends(days=settings.analytics_default_days)
        previous_summary = self._latest_prediction_summary()
        possible_results = analytics_service.build_possible_results_summary(previous_summary=previous_summary)
        backtesting = analytics_service.build_backtesting_summary(days=settings.analytics_default_days)
        self._persist_default_snapshots(
            overview=overview,
            trends=trends,
            possible_results=possible_results,
            backtesting=backtesting,
        )

        if notify and save_stats["new_results"]:
            await telegram_service.send_results_digest(save_stats["new_results"], ingestion_run)
        if notify and status in {"failed", "partial"}:
            await telegram_service.send_ingestion_alert(ingestion_run)
        if save_stats["new_count"] > 0:
            await self.send_today_possible_results(
                preview_only=not (notify and settings.prediction_auto_send_on_refresh),
                trigger_context="refresh-update",
                previous_summary=previous_summary,
                summary=possible_results,
            )
        elif notify:
            await self.send_due_pre_draw_alerts(summary=possible_results)
        log_event(
            logging.getLogger(__name__),
            logging.INFO,
            "refresh_today_completed",
            trigger=trigger,
            status=status,
            results_found=len(scrape_payload["results"]),
            new_results=save_stats["new_count"],
        )

        return {
            "ingestion_run": ingestion_run,
            "overview": overview.model_dump(),
        }

    async def _execute_backfill(
        self,
        request: BackfillRequest,
        trigger: str = "manual",
        progress_callback=None,
    ) -> dict:
        start_date, end_date, total_days = self._resolve_backfill_range(request)

        inserted_total = 0
        duplicates_total = 0
        results_total = 0
        empty_days = []
        errors = []
        source_urls = []
        lotteries_seen = set()
        started_at = utc_now()
        source_reports = []
        current_date = start_date
        completed_days = 0

        while current_date <= end_date:
            if progress_callback:
                progress_callback(
                    status="running",
                    message=f"Procesando {current_date.isoformat()} ({completed_days + 1}/{total_days})",
                    current_date=current_date,
                    completed_days=completed_days,
                    results_found=results_total,
                    new_results=inserted_total,
                    duplicates=duplicates_total,
                    empty_days=list(empty_days),
                    errors_count=len(errors),
                    last_error=errors[-1] if errors else None,
                )

            scrape_payload = await scraper_service.fetch_results_for_date(current_date)
            source_urls.extend(scrape_payload["source_urls"])
            errors.extend(scrape_payload["errors"])
            source_reports.extend(scrape_payload.get("source_reports", []))
            results_total += len(scrape_payload["results"])

            if not scrape_payload["results"]:
                empty_days.append(current_date.isoformat())
            else:
                save_stats = db_service.upsert_results(scrape_payload["results"])
                inserted_total += save_stats["new_count"]
                duplicates_total += save_stats["duplicate_count"]
                for result in scrape_payload["results"]:
                    lotteries_seen.add(result["canonical_lottery_name"])

            completed_days += 1
            if progress_callback:
                progress_callback(
                    status="running",
                    message=f"{completed_days} de {total_days} dias procesados",
                    current_date=current_date,
                    completed_days=completed_days,
                    results_found=results_total,
                    new_results=inserted_total,
                    duplicates=duplicates_total,
                    empty_days=list(empty_days),
                    errors_count=len(errors),
                    last_error=errors[-1] if errors else None,
                )

            current_date += timedelta(days=1)
            await asyncio.sleep(0)

        completed_at = utc_now()
        status = "success" if not errors else "partial"
        missing_slots, source_status = self._build_run_quality_metadata(
            start_date=start_date,
            end_date=end_date,
            source_reports=source_reports,
        )
        run = {
            "trigger": f"{trigger}:backfill",
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round((completed_at - started_at).total_seconds(), 2),
            "results_found": results_total,
            "new_results": inserted_total,
            "duplicates": duplicates_total,
            "errors": errors,
            "source_urls": sorted(set(source_urls)),
            "lotteries_seen": sorted(lotteries_seen),
            "coverage_start": start_date,
            "coverage_end": end_date,
            "parser_version": scraper_service.PARSER_VERSION,
            "missing_slots": missing_slots,
            "source_status": source_status,
            "source_reports": source_reports,
        }
        run["id"] = db_service.save_ingestion_run(run)

        if progress_callback:
            progress_callback(
                status="finalizing",
                message="Recalculando snapshots y analitica del panel",
                completed_days=total_days,
                current_date=end_date,
                results_found=results_total,
                new_results=inserted_total,
                duplicates=duplicates_total,
                empty_days=list(empty_days),
                errors_count=len(errors),
                last_error=errors[-1] if errors else None,
                ingestion_run_id=run["id"],
            )

        previous_summary = self._latest_prediction_summary()
        self._persist_default_snapshots(
            overview=analytics_service.build_dashboard_overview(),
            trends=analytics_service.build_trends(days=settings.analytics_default_days),
            possible_results=analytics_service.build_possible_results_summary(previous_summary=previous_summary),
            backtesting=analytics_service.build_backtesting_summary(days=settings.analytics_default_days),
        )
        log_event(
            logging.getLogger(__name__),
            logging.INFO,
            "backfill_completed",
            trigger=trigger,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            new_results=inserted_total,
            duplicates=duplicates_total,
        )

        return {
            "message": "Backfill completed",
            "details": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "results_found": results_total,
                "new_results": inserted_total,
                "duplicates": duplicates_total,
                "empty_days": empty_days,
                "errors_count": len(errors),
                "status": status,
                "total_days": total_days,
                "ingestion_run_id": run["id"],
            },
        }

    async def _run_backfill_job(self, request: BackfillRequest, trigger: str, snapshot: dict) -> None:
        current_snapshot = self._update_backfill_snapshot(
            snapshot,
            status="running",
            message="Backfill iniciado en segundo plano.",
        )

        def progress_callback(**updates):
            nonlocal current_snapshot
            current_snapshot = self._update_backfill_snapshot(current_snapshot, **updates)

        try:
            response = await self._execute_backfill(
                request=request,
                trigger=trigger,
                progress_callback=progress_callback,
            )
            final_status = response["details"].get("status", "success")
            final_label = "completed" if final_status == "success" else final_status
            current_snapshot = self._update_backfill_snapshot(
                current_snapshot,
                status=final_label,
                message="Backfill finalizado y snapshots actualizados.",
                completed_days=current_snapshot.get("total_days", current_snapshot.get("completed_days", 0)),
                completed_at=utc_now(),
                ingestion_run_id=response["details"].get("ingestion_run_id"),
                results_found=response["details"].get("results_found", 0),
                new_results=response["details"].get("new_results", 0),
                duplicates=response["details"].get("duplicates", 0),
                empty_days=response["details"].get("empty_days", []),
                errors_count=response["details"].get("errors_count", 0),
                current_date=current_snapshot.get("end_date"),
            )
        except Exception as exc:
            current_snapshot = self._update_backfill_snapshot(
                current_snapshot,
                status="failed",
                message="El backfill fallo antes de completarse.",
                last_error=str(exc),
                errors_count=(current_snapshot.get("errors_count") or 0) + 1,
                completed_at=utc_now(),
            )
            raise
        finally:
            self._backfill_task = None

    async def backfill(self, request: BackfillRequest, trigger: str = "manual") -> dict:
        return await self._execute_backfill(request=request, trigger=trigger)

    async def run_due_scheduler_cycle(self) -> dict:
        now_local = local_now()
        schedules = db_service.get_schedules()
        latest_run = db_service.get_latest_ingestion_run()

        if not schedules:
            return {"skipped": True, "reason": "no schedules"}

        active_times = [time_value for schedule in schedules for time_value in schedule.get("times", [])]
        if not active_times:
            return {"skipped": True, "reason": "no times"}

        earliest = min(active_times)
        latest = max(active_times)
        current_time = now_local.strftime("%H:%M")
        if current_time < earliest or current_time > latest:
            return {"skipped": True, "reason": "outside active window"}

        should_run = False
        lookback_delta = timedelta(minutes=settings.scheduler_lookback_minutes)
        for schedule in schedules:
            for draw_time_local in schedule.get("times", []):
                draw_hour, draw_minute = map(int, draw_time_local.split(":"))
                candidate = now_local.replace(hour=draw_hour, minute=draw_minute, second=0, microsecond=0)
                if timedelta(0) <= (now_local - candidate) <= lookback_delta:
                    should_run = True
                    break
            if should_run:
                break

        if latest_run and latest_run.get("completed_at"):
            min_gap = timedelta(minutes=settings.scheduler_min_gap_minutes)
            if (utc_now() - latest_run["completed_at"]) < min_gap:
                return {"skipped": True, "reason": "recent run"}

        if not should_run:
            return {"skipped": True, "reason": "no due draws"}

        return await self.refresh_today(trigger="scheduler", notify=True)

    async def send_daily_summary(self) -> bool:
        overview = analytics_service.build_dashboard_overview()
        return await telegram_service.send_daily_summary(overview.model_dump())

    async def send_today_possible_results(
        self,
        top_n: int | None = None,
        lotteries: list[str] | None = None,
        preview_only: bool = False,
        trigger_context: str = "manual-summary",
        previous_summary: dict | None = None,
        summary=None,
    ) -> dict:
        summary = summary or analytics_service.build_possible_results_summary(
            top_n=top_n,
            lotteries=lotteries,
            previous_summary=previous_summary,
        )
        sent = False
        delivery_status = "preview"
        if not preview_only:
            sent = await telegram_service.send_possible_results_summary(summary.model_dump())
            delivery_status = "sent" if sent else "failed"

        summary_payload = summary.model_dump()
        summary_payload["delivery_context"] = {
            "kind": trigger_context,
            "change_alerts_count": len(summary.change_alerts),
        }
        run_payload = {
            "generated_at": summary.generated_at,
            "delivery_status": delivery_status,
            "preview_only": preview_only,
            "target_lotteries": [item.canonical_lottery_name for item in summary.lotteries],
            "top_n": top_n or settings.prediction_default_top_n,
            "summary": summary_payload,
            "telegram_sent": sent,
        }
        prediction_run_id = db_service.save_prediction_run(run_payload)
        backtesting = analytics_service.build_backtesting_summary(lotteries=lotteries, top_n=top_n)
        log_event(
            logging.getLogger(__name__),
            logging.INFO,
            "possible_results_processed",
            sent=sent,
            preview_only=preview_only,
            prediction_run_id=prediction_run_id,
        )

        return {
            "message": "Statistical possible-results summary processed",
            "details": {
                "prediction_run_id": prediction_run_id,
                "sent": sent,
                "lotteries": len(summary.lotteries),
                "generated_at": summary.generated_at,
                "summary": summary.model_dump(),
                "backtesting": backtesting.model_dump(),
                "preview_only": preview_only,
            },
        }

    async def send_due_pre_draw_alerts(self, summary=None) -> dict:
        summary = summary or analytics_service.build_possible_results_summary(previous_summary=self._latest_prediction_summary())
        alerts = self._collect_pre_draw_alerts(summary)
        if not alerts:
            return {"sent": False, "alerts": []}

        sent = await telegram_service.send_pre_draw_alerts(alerts)
        summary_payload = summary.model_dump()
        summary_payload["delivery_context"] = {
            "kind": "pre-draw-alert",
            "alerted_window_keys": [item["window_key"] for item in alerts],
        }
        prediction_run_id = db_service.save_prediction_run(
            {
                "generated_at": summary.generated_at,
                "delivery_status": "sent" if sent else "failed",
                "preview_only": False,
                "target_lotteries": [item.canonical_lottery_name for item in summary.lotteries],
                "top_n": settings.prediction_default_top_n,
                "summary": summary_payload,
                "telegram_sent": sent,
            }
        )
        return {"sent": sent, "alerts": alerts, "prediction_run_id": prediction_run_id}

    async def run_weekly_recovery_backfill(self) -> dict:
        return await self.backfill(
            request=BackfillRequest(days=7),
            trigger="scheduler-weekly",
        )


monitoring_service = MonitoringService()
