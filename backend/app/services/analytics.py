from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from app.core.config import settings
from app.core.lottery_catalog import EXPECTED_RESULTS_PER_DAY, PRIMARY_LOTTERIES
from app.models.schemas import (
    AnalyticsTrends,
    AuditLogEntry,
    BacktestingHourMetric,
    BacktestingLotteryMetric,
    BacktestingSummary,
    DashboardOverview,
    DrawPredictionCandidate,
    DrawPredictionWindow,
    IngestionRun,
    LotteryOverviewCard,
    LotteryPossibleResults,
    PossibleResultCandidate,
    PossibleResultsSummary,
    QualityLotteryRecord,
    QualityReportResponse,
    ScoreComponent,
    SystemStatusResponse,
    TrendBucket,
)
from app.services.database import db_service
from app.services.schedule import build_next_draw, expected_draws_by_now, local_now, parse_time_local, utc_now
from app.services.telegram import telegram_service


SCORE_COMPONENTS = [
    ScoreComponent(key="recent_slot_frequency", label="Frecuencia reciente por hora", weight=0.24),
    ScoreComponent(key="historical_slot_frequency", label="Frecuencia historica por hora", weight=0.22),
    ScoreComponent(key="transition_match", label="Transicion desde el ultimo resultado", weight=0.18),
    ScoreComponent(key="coincidence_match", label="Coincidencia con el patron del dia", weight=0.16),
    ScoreComponent(key="recent_frequency", label="Frecuencia reciente global", weight=0.12),
    ScoreComponent(key="historical_frequency", label="Frecuencia historica global", weight=0.05),
    ScoreComponent(key="overdue_gap", label="Rezago desde ultima aparicion", weight=0.03),
]


class AnalyticsService:
    METHODOLOGY_VERSION = "ops-coincidence-v3"
    MINIMUM_BACKTEST_HISTORY = 10

    @staticmethod
    def _coerce_datetime(value) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"Unsupported datetime value: {value!r}")

    @staticmethod
    def _coerce_date_string(value) -> str:
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _normalize_lotteries(self, lotteries: list[str] | None = None) -> list[str]:
        if not lotteries:
            return list(PRIMARY_LOTTERIES)
        allowed = set(PRIMARY_LOTTERIES)
        return [lottery for lottery in lotteries if lottery in allowed]

    def _get_target_draw_times(self, schedule: dict, reference_local: datetime) -> list[str]:
        remaining = []
        for draw_time_local in schedule.get("times", []):
            parsed = parse_time_local(draw_time_local)
            candidate = reference_local.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=0,
                microsecond=0,
            )
            if candidate >= reference_local:
                remaining.append(draw_time_local)
        return remaining or list(schedule.get("times", []))

    def _sort_results(self, results: list[dict], reverse: bool = False) -> list[dict]:
        return sorted(results, key=lambda item: self._coerce_datetime(item["draw_datetime_utc"]), reverse=reverse)

    def _group_results_by_day(self, results: list[dict]) -> dict[str, list[dict]]:
        grouped = defaultdict(list)
        for result in results:
            grouped[self._coerce_date_string(result["draw_date"])].append(result)
        return {draw_date: self._sort_results(items) for draw_date, items in grouped.items()}

    def _build_draw_prediction_window(
        self,
        target_draw_time: str,
        today_results: list[dict],
        historical_days: dict[str, list[dict]],
        overall_counter: Counter,
        recent_counter: Counter,
        last_seen_draws: dict,
        recent_cutoff: datetime,
        top_n: int,
    ) -> DrawPredictionWindow:
        slot_counter = Counter()
        recent_slot_counter = Counter()
        transition_counter = Counter()
        coincidence_counter = Counter()

        observed_prefix_results = [item for item in today_results if item["draw_time_local"] < target_draw_time]
        observed_prefix = [item["animal_number"] for item in observed_prefix_results]
        last_today_number = observed_prefix[-1] if observed_prefix else None

        for day_items in historical_days.values():
            by_time = {item["draw_time_local"]: item for item in day_items}
            target_item = by_time.get(target_draw_time)
            if not target_item:
                continue

            target_key = (target_item["animal_number"], target_item["animal_name"])
            slot_counter[target_key] += 1
            if self._coerce_datetime(target_item["draw_datetime_utc"]) >= recent_cutoff:
                recent_slot_counter[target_key] += 1

            before_items = [item for item in day_items if item["draw_time_local"] < target_draw_time]
            if last_today_number is not None and before_items and before_items[-1]["animal_number"] == last_today_number:
                transition_counter[target_key] += 1

            if observed_prefix:
                historical_prefix_numbers = {item["animal_number"] for item in before_items}
                overlap = len(set(observed_prefix) & historical_prefix_numbers)
                if overlap > 0:
                    coincidence_counter[target_key] += overlap

        slot_max = max(slot_counter.values(), default=1)
        recent_slot_max = max(recent_slot_counter.values(), default=1)
        transition_max = max(transition_counter.values(), default=1)
        coincidence_max = max(coincidence_counter.values(), default=1)
        overall_max = max(overall_counter.values(), default=1)
        recent_max = max(recent_counter.values(), default=1)
        overdue_max = max(last_seen_draws.values(), default=0) or 1

        candidate_keys = set(overall_counter) | set(slot_counter) | set(transition_counter) | set(coincidence_counter)
        candidates = []
        for animal_number, animal_name in candidate_keys:
            overall_hits = overall_counter.get((animal_number, animal_name), 0)
            recent_hits = recent_counter.get((animal_number, animal_name), 0)
            slot_hits = slot_counter.get((animal_number, animal_name), 0)
            recent_slot_hits = recent_slot_counter.get((animal_number, animal_name), 0)
            transition_hits = transition_counter.get((animal_number, animal_name), 0)
            coincidence_hits = coincidence_counter.get((animal_number, animal_name), 0)
            draws_since_last_seen = last_seen_draws.get((animal_number, animal_name), 0)

            score = (
                (recent_slot_hits / recent_slot_max) * 0.24
                + (slot_hits / slot_max) * 0.22
                + (transition_hits / transition_max) * 0.18
                + (coincidence_hits / coincidence_max) * 0.16
                + (recent_hits / recent_max) * 0.12
                + (overall_hits / overall_max) * 0.05
                + (draws_since_last_seen / overdue_max) * 0.03
            )

            candidates.append(
                DrawPredictionCandidate(
                    animal_number=animal_number,
                    animal_name=animal_name,
                    score=round(score * 100, 2),
                    slot_hits=slot_hits,
                    recent_slot_hits=recent_slot_hits,
                    transition_hits=transition_hits,
                    coincidence_hits=coincidence_hits,
                    overall_hits=overall_hits,
                    recent_hits=recent_hits,
                    draws_since_last_seen=draws_since_last_seen,
                )
            )

        candidates.sort(
            key=lambda item: (
                item.score,
                item.transition_hits,
                item.coincidence_hits,
                item.recent_slot_hits,
                item.slot_hits,
                item.recent_hits,
            ),
            reverse=True,
        )

        return DrawPredictionWindow(
            draw_time_local=target_draw_time,
            observed_prefix=observed_prefix,
            candidates=candidates[:top_n],
        )

    def _build_candidates_for_reference(
        self,
        lottery_name: str,
        results: list[dict],
        schedule: dict,
        reference_local: datetime,
        top_n: int,
    ) -> LotteryPossibleResults | None:
        if not results:
            return None

        sorted_desc = self._sort_results(results, reverse=True)
        sorted_asc = list(reversed(sorted_desc))
        reference_date_str = reference_local.date().isoformat()
        recent_cutoff = reference_local - timedelta(days=min(settings.analytics_default_days, 21))
        target_draw_times = self._get_target_draw_times(schedule, reference_local)

        overall_counter = Counter()
        recent_counter = Counter()
        last_seen_draws = {}
        date_span = set()

        for index, result in enumerate(sorted_desc):
            key = (result["animal_number"], result.get("animal_name") or f"Animal {result['animal_number']:02d}")
            draw_dt = self._coerce_datetime(result["draw_datetime_utc"])
            draw_date = self._coerce_date_string(result["draw_date"])
            overall_counter[key] += 1
            if draw_dt >= recent_cutoff:
                recent_counter[key] += 1
            date_span.add(draw_date)
            if key not in last_seen_draws:
                last_seen_draws[key] = index

        today_results = [item for item in sorted_asc if self._coerce_date_string(item["draw_date"]) == reference_date_str]
        historical_days = {
            draw_date: items
            for draw_date, items in self._group_results_by_day(results).items()
            if draw_date != reference_date_str
        }

        draw_predictions = [
            self._build_draw_prediction_window(
                target_draw_time=draw_time_local,
                today_results=today_results,
                historical_days=historical_days,
                overall_counter=overall_counter,
                recent_counter=recent_counter,
                last_seen_draws=last_seen_draws,
                recent_cutoff=recent_cutoff,
                top_n=top_n,
            )
            for draw_time_local in target_draw_times
        ]

        next_draw = build_next_draw(schedule, reference_local) if schedule else None
        next_candidates = draw_predictions[0].candidates if draw_predictions else []
        candidates = [
            PossibleResultCandidate(
                animal_number=item.animal_number,
                animal_name=item.animal_name,
                score=item.score,
                overall_hits=item.overall_hits,
                recent_hits=item.recent_hits,
                remaining_time_hits=item.slot_hits,
                draws_since_last_seen=item.draws_since_last_seen,
                seen_today=item.animal_number in {result["animal_number"] for result in today_results},
            )
            for item in next_candidates
        ]

        return LotteryPossibleResults(
            canonical_lottery_name=lottery_name,
            history_results_considered=len(sorted_desc),
            history_days_covered=len(date_span),
            today_results_count=len(today_results),
            remaining_draws_today=len(target_draw_times),
            next_draw_time_local=next_draw["draw_time_local"] if next_draw else None,
            target_draw_times=target_draw_times,
            candidates=candidates,
            draw_predictions=draw_predictions,
        )

    def build_dashboard_overview(self) -> DashboardOverview:
        now_local = local_now()
        today_str = now_local.date().isoformat()
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        today_results = db_service.get_results(start_date=today_str, end_date=today_str, limit=500)
        latest_results = today_results[:10]
        latest_run = db_service.get_latest_ingestion_run()

        next_draw = None
        for schedule in schedules.values():
            candidate = build_next_draw(schedule, now_local)
            if candidate and (not next_draw or candidate["draw_datetime_utc"] < next_draw["draw_datetime_utc"]):
                next_draw = candidate

        cards = []
        missing_total = 0
        for lottery_name in PRIMARY_LOTTERIES:
            lottery_results = [item for item in today_results if item["canonical_lottery_name"] == lottery_name]
            schedule = schedules.get(lottery_name, {"times": []})
            expected_today = EXPECTED_RESULTS_PER_DAY.get(lottery_name, len(schedule.get("times", [])))
            expected_now = expected_draws_by_now(schedule, now_local) if schedule else 0
            missing_today = max(expected_now - len(lottery_results), 0)
            missing_total += missing_today

            next_time = build_next_draw(schedule, now_local) if schedule else None
            cards.append(
                LotteryOverviewCard(
                    canonical_lottery_name=lottery_name,
                    total_results_today=len(lottery_results),
                    expected_results_today=expected_today,
                    expected_by_now=expected_now,
                    missing_draws_today=missing_today,
                    completion_ratio=(len(lottery_results) / expected_today) if expected_today else 0,
                    last_result=lottery_results[0] if lottery_results else None,
                    next_draw_time_local=next_time["draw_time_local"] if next_time else None,
                )
            )

        return DashboardOverview(
            generated_at=utc_now(),
            total_results_today=len(today_results),
            missing_draws_today=missing_total,
            next_draw=next_draw,
            latest_results=latest_results,
            primary_lotteries=cards,
            latest_ingestion_run=IngestionRun.model_validate(latest_run) if latest_run else None,
        )

    def build_trends(self, lottery_name: str | None = None, days: int | None = None) -> AnalyticsTrends:
        days = days or settings.analytics_default_days
        now_local = local_now()
        start_date = (now_local.date() - timedelta(days=days - 1)).isoformat()
        end_date = now_local.date().isoformat()
        results = db_service.get_results(
            canonical_lottery_name=lottery_name,
            start_date=start_date,
            end_date=end_date,
            limit=5000,
        )

        frequency_counter = Counter()
        hourly_counter = Counter()
        daily_counter = Counter()
        streaks = []
        anomalies = []

        grouped = defaultdict(list)
        for result in results:
            grouped[result["canonical_lottery_name"]].append(result)
            frequency_counter[(result["canonical_lottery_name"], result["animal_number"], result["animal_name"])] += 1
            hourly_counter[(result["canonical_lottery_name"], result["draw_time_local"])] += 1
            daily_counter[(result["canonical_lottery_name"], self._coerce_date_string(result["draw_date"]))] += 1

        for current_lottery, items in grouped.items():
            sorted_items = self._sort_results(items, reverse=True)
            repeated = 1
            for index in range(1, len(sorted_items)):
                if sorted_items[index]["animal_number"] == sorted_items[index - 1]["animal_number"]:
                    repeated += 1
                else:
                    break

            if sorted_items:
                streaks.append(
                    {
                        "lottery_name": current_lottery,
                        "current_animal_number": sorted_items[0]["animal_number"],
                        "current_animal_name": sorted_items[0]["animal_name"],
                        "repeat_streak": repeated,
                        "last_draw_time_local": sorted_items[0]["draw_time_local"],
                    }
                )

            expected = EXPECTED_RESULTS_PER_DAY.get(current_lottery)
            daily_counts = Counter(self._coerce_date_string(item["draw_date"]) for item in items)
            for draw_date, count in daily_counts.items():
                if expected and count < expected:
                    anomalies.append(
                        {
                            "lottery_name": current_lottery,
                            "draw_date": draw_date,
                            "missing_results": expected - count,
                        }
                    )

        frequency = [
            TrendBucket(
                label=f"{animal_number:02d}",
                value=count,
                lottery_name=lottery,
                animal_number=animal_number,
                animal_name=animal_name,
            )
            for (lottery, animal_number, animal_name), count in frequency_counter.most_common(12)
        ]

        hourly_distribution = [
            TrendBucket(label=time_label, value=count, lottery_name=lottery)
            for (lottery, time_label), count in sorted(hourly_counter.items(), key=lambda item: (item[0][0], item[0][1]))
        ]

        daily_volume = [
            TrendBucket(label=draw_date, value=count, lottery_name=lottery)
            for (lottery, draw_date), count in sorted(daily_counter.items(), key=lambda item: (item[0][1], item[0][0]))
        ]

        return AnalyticsTrends(
            generated_at=utc_now(),
            days=days,
            lottery_name=lottery_name,
            frequency=frequency,
            hourly_distribution=hourly_distribution,
            daily_volume=daily_volume,
            streaks=streaks,
            anomalies=anomalies[:20],
        )

    def build_possible_results_summary(
        self,
        top_n: int | None = None,
        lotteries: list[str] | None = None,
        reference_local: datetime | None = None,
    ) -> PossibleResultsSummary:
        top_n = top_n or settings.prediction_default_top_n
        reference_local = reference_local or local_now()
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        selected_lotteries = self._normalize_lotteries(lotteries)
        summary_items = []
        unique_dates = set()
        total_history_results = 0

        for lottery_name in selected_lotteries:
            results = db_service.get_results(canonical_lottery_name=lottery_name, limit=None)
            schedule = schedules.get(lottery_name, {"times": []})
            lottery_summary = self._build_candidates_for_reference(
                lottery_name=lottery_name,
                results=results,
                schedule=schedule,
                reference_local=reference_local,
                top_n=top_n,
            )
            if lottery_summary:
                summary_items.append(lottery_summary)
                total_history_results += lottery_summary.history_results_considered
                unique_dates.update(self._coerce_date_string(result["draw_date"]) for result in results)

        latest_backfill = db_service.get_latest_backfill_run()
        return PossibleResultsSummary(
            generated_at=utc_now(),
            methodology_version=self.METHODOLOGY_VERSION,
            methodology=(
                "Prediccion estadistica operativa basada en frecuencia por hora, transiciones entre sorteos, "
                "coincidencias del patron del dia, frecuencia historica y rezago de aparicion."
            ),
            disclaimer="Proyeccion estadistica. No garantiza aciertos ni reemplaza criterio operativo.",
            history_days_covered=len(unique_dates),
            history_results_considered=total_history_results,
            score_components=list(SCORE_COMPONENTS),
            last_backfill_at=latest_backfill.get("completed_at") if latest_backfill else None,
            lotteries=summary_items,
        )

    def build_backtesting_summary(
        self,
        days: int | None = None,
        top_n: int | None = None,
        lotteries: list[str] | None = None,
    ) -> BacktestingSummary:
        days = days or settings.analytics_default_days
        top_n = max(top_n or settings.prediction_default_top_n, 5)
        selected_lotteries = self._normalize_lotteries(lotteries)
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        now_local = local_now()
        start_date = (now_local.date() - timedelta(days=days - 1)).isoformat()
        end_date = now_local.date().isoformat()

        lottery_stats = defaultdict(lambda: {"total": 0, "top1": 0, "top3": 0, "top5": 0})
        hour_stats = defaultdict(lambda: {"total": 0, "top1": 0, "top3": 0, "top5": 0})

        for lottery_name in selected_lotteries:
            items = db_service.get_results(
                canonical_lottery_name=lottery_name,
                start_date=start_date,
                end_date=end_date,
                limit=None,
            )
            ordered = self._sort_results(items)
            schedule = schedules.get(lottery_name, {"times": []})

            for index, actual in enumerate(ordered):
                history = ordered[:index]
                if len(history) < self.MINIMUM_BACKTEST_HISTORY:
                    continue

                draw_date_value = actual["draw_date"]
                if isinstance(draw_date_value, str):
                    draw_date_value = date.fromisoformat(draw_date_value)
                reference_local = datetime.combine(
                    draw_date_value,
                    parse_time_local(actual["draw_time_local"]),
                    tzinfo=local_now().tzinfo,
                )
                candidate_summary = self._build_candidates_for_reference(
                    lottery_name=lottery_name,
                    results=history,
                    schedule=schedule,
                    reference_local=reference_local,
                    top_n=top_n,
                )
                if not candidate_summary:
                    continue

                target_window = next(
                    (
                        window
                        for window in candidate_summary.draw_predictions
                        if window.draw_time_local == actual["draw_time_local"]
                    ),
                    None,
                )
                ranked_numbers = [
                    candidate.animal_number for candidate in (target_window.candidates if target_window else candidate_summary.candidates)
                ]
                actual_number = actual["animal_number"]
                lottery_stats[lottery_name]["total"] += 1
                hour_key = (lottery_name, actual["draw_time_local"])
                hour_stats[hour_key]["total"] += 1

                if ranked_numbers[:1] and actual_number in ranked_numbers[:1]:
                    lottery_stats[lottery_name]["top1"] += 1
                    hour_stats[hour_key]["top1"] += 1
                if actual_number in ranked_numbers[:3]:
                    lottery_stats[lottery_name]["top3"] += 1
                    hour_stats[hour_key]["top3"] += 1
                if actual_number in ranked_numbers[:5]:
                    lottery_stats[lottery_name]["top5"] += 1
                    hour_stats[hour_key]["top5"] += 1

        by_lottery = []
        overall_total = 0
        overall_top1 = 0
        overall_top3 = 0
        overall_top5 = 0
        for lottery_name in selected_lotteries:
            stats = lottery_stats[lottery_name]
            total = stats["total"]
            overall_total += total
            overall_top1 += stats["top1"]
            overall_top3 += stats["top3"]
            overall_top5 += stats["top5"]
            by_lottery.append(
                BacktestingLotteryMetric(
                    lottery_name=lottery_name,
                    total_draws=total,
                    top_1_hits=stats["top1"],
                    top_3_hits=stats["top3"],
                    top_5_hits=stats["top5"],
                    top_1_rate=round((stats["top1"] / total) if total else 0, 4),
                    top_3_rate=round((stats["top3"] / total) if total else 0, 4),
                    top_5_rate=round((stats["top5"] / total) if total else 0, 4),
                )
            )

        by_hour = [
            BacktestingHourMetric(
                lottery_name=lottery_name,
                draw_time_local=draw_time_local,
                total_draws=stats["total"],
                top_1_hits=stats["top1"],
                top_3_hits=stats["top3"],
                top_5_hits=stats["top5"],
            )
            for (lottery_name, draw_time_local), stats in sorted(hour_stats.items(), key=lambda item: (item[0][0], item[0][1]))
        ]

        return BacktestingSummary(
            generated_at=utc_now(),
            days=days,
            methodology_version=self.METHODOLOGY_VERSION,
            overall_total_draws=overall_total,
            overall_top_1_rate=round((overall_top1 / overall_total) if overall_total else 0, 4),
            overall_top_3_rate=round((overall_top3 / overall_total) if overall_total else 0, 4),
            overall_top_5_rate=round((overall_top5 / overall_total) if overall_total else 0, 4),
            by_lottery=by_lottery,
            by_hour=by_hour,
        )

    def build_quality_report(self, days: int | None = None, lotteries: list[str] | None = None) -> QualityReportResponse:
        days = days or settings.quality_default_days
        selected_lotteries = self._normalize_lotteries(lotteries)
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        now_local = local_now()
        start_date_obj = now_local.date() - timedelta(days=days - 1)
        end_date_obj = now_local.date()
        all_results = db_service.get_results(
            start_date=start_date_obj.isoformat(),
            end_date=end_date_obj.isoformat(),
            limit=None,
        )

        grouped_results = defaultdict(set)
        for result in all_results:
            grouped_results[(self._coerce_date_string(result["draw_date"]), result["canonical_lottery_name"])].add(
                result["draw_time_local"]
            )

        source_status_map = {}
        for run in db_service.get_ingestion_runs(limit=None):
            for report in run.get("source_reports", []):
                key = (report.get("draw_date"), report.get("source_page"))
                if key not in source_status_map:
                    source_status_map[key] = report.get("status")

        items = []
        current_date = start_date_obj
        while current_date <= end_date_obj:
            date_key = current_date.isoformat()
            for lottery_name in selected_lotteries:
                schedule = schedules.get(lottery_name, {"times": [], "source_pages": []})
                expected_times = list(schedule.get("times", []))
                found_times = grouped_results.get((date_key, lottery_name), set())
                missing_slots = [time_value for time_value in expected_times if time_value not in found_times]
                source_page = (schedule.get("source_pages") or [None])[0]
                source_status = source_status_map.get((date_key, source_page))

                if len(found_times) >= len(expected_times) and expected_times:
                    state = "complete"
                elif source_status == "error" and missing_slots:
                    state = "source-error"
                elif not found_times:
                    state = "missing"
                else:
                    state = "partial"

                items.append(
                    QualityLotteryRecord(
                        draw_date=current_date,
                        canonical_lottery_name=lottery_name,
                        expected_slots=len(expected_times),
                        found_slots=len(found_times),
                        missing_slots=missing_slots,
                        status=state,
                        source_status=source_status,
                        coverage_ratio=round((len(found_times) / len(expected_times)) if expected_times else 0, 4),
                    )
                )
            current_date += timedelta(days=1)

        items.sort(key=lambda item: (item.draw_date, item.canonical_lottery_name), reverse=True)
        return QualityReportResponse(generated_at=utc_now(), days=days, items=items)

    def build_system_status(self, scheduler_running: bool) -> SystemStatusResponse:
        ingestion_runs = db_service.get_ingestion_runs(limit=100)
        latest_successful = next((run for run in ingestion_runs if run.get("status") in {"success", "partial", "empty"}), None)
        latest_failed = next((run for run in ingestion_runs if run.get("status") == "failed"), None)
        latest_backfill = db_service.get_latest_backfill_run()
        latest_prediction = db_service.get_latest_prediction_run()

        warnings = []
        if settings.jwt_secret_key == "super-secret-key-change-in-production":
            warnings.append("JWT secret is using the default project value.")
        if not settings.bootstrap_admin_password and not settings.bootstrap_admin_token:
            warnings.append("No bootstrap admin credentials or token configured.")
        if not telegram_service.configured:
            warnings.append("Telegram is not configured.")
        if not latest_backfill:
            warnings.append("No backfill has been executed yet.")
        if settings.use_external_scheduler and not settings.scheduler_service_token:
            warnings.append("External scheduler mode is enabled but scheduler token is empty.")

        database_provider = "mock"
        if db_service.is_postgres_mode:
            database_provider = "postgres"
        elif db_service.is_firestore_mode:
            database_provider = "firestore"

        return SystemStatusResponse(
            generated_at=utc_now(),
            firebase_connected=not db_service.is_mock_mode,
            database_provider=database_provider,
            telegram_configured=telegram_service.configured,
            scheduler_running=scheduler_running,
            latest_successful_run=IngestionRun.model_validate(latest_successful) if latest_successful else None,
            latest_failed_run=IngestionRun.model_validate(latest_failed) if latest_failed else None,
            latest_backfill_run=IngestionRun.model_validate(latest_backfill) if latest_backfill else None,
            latest_prediction_run=latest_prediction,
            total_results=db_service.count_results(),
            warnings=warnings,
        )

    def build_audit_entries(self, limit: int | None = None) -> list[AuditLogEntry]:
        limit = limit or settings.admin_audit_default_limit
        return [AuditLogEntry.model_validate(item) for item in db_service.get_audit_logs(limit=limit)]


analytics_service = AnalyticsService()
