from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.core.lottery_catalog import EXPECTED_RESULTS_PER_DAY, PRIMARY_LOTTERIES
from app.models.schemas import (
    ANIMALITOS_MAP,
    AnalyticsTrends,
    AuditLogEntry,
    BackfillJobStatus,
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
    get_animal_name,
)
from app.services.database import db_service
from app.services.schedule import build_next_draw, expected_draws_by_now, local_now, parse_time_local, utc_now
from app.services.telegram import telegram_service


SCORE_COMPONENTS = [
    ScoreComponent(key="slot_recent_14d", label="Frecuencia reciente por hora (14d)", weight=0.16),
    ScoreComponent(key="slot_historical_90d", label="Frecuencia historica por hora (90d)", weight=0.10),
    ScoreComponent(key="weekday_slot_frequency", label="Coincidencia por dia de semana y hora", weight=0.08),
    ScoreComponent(key="daypart_frequency", label="Frecuencia por tramo del dia", weight=0.06),
    ScoreComponent(key="recent_frequency_7d", label="Frecuencia global reciente (7d)", weight=0.08),
    ScoreComponent(key="recent_frequency_30d", label="Frecuencia global reciente (30d)", weight=0.06),
    ScoreComponent(key="historical_frequency_90d", label="Frecuencia global historica (90d)", weight=0.04),
    ScoreComponent(key="last_transition", label="Transicion desde el ultimo resultado", weight=0.10),
    ScoreComponent(key="pair_context", label="Pareja previa coincidente", weight=0.08),
    ScoreComponent(key="trio_context", label="Trio previo coincidente", weight=0.06),
    ScoreComponent(key="prefix_overlap", label="Coincidencias con el patron del dia", weight=0.08),
    ScoreComponent(key="exact_prefix_match", label="Ruta exacta del dia", weight=0.04),
    ScoreComponent(key="overdue_gap", label="Rezago desde ultima aparicion", weight=0.04),
    ScoreComponent(key="same_day_repeat_pattern", label="Patron de repeticion intradia", weight=0.02),
]


class AnalyticsService:
    METHODOLOGY_VERSION = "ops-intraday-ranking-v4"
    BASELINE_METHODOLOGY_VERSION = "frequency-baseline-v1"
    MINIMUM_BACKTEST_HISTORY = 10
    FULL_TOP_N = 10

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

    @staticmethod
    def _daypart_for_time(draw_time_local: str) -> str:
        hour = parse_time_local(draw_time_local).hour
        if hour < 12:
            return "manana"
        if hour < 16:
            return "tarde"
        return "noche"

    @staticmethod
    def _normalize(value: int | float, maximum: int | float) -> float:
        if not maximum:
            return 0.0
        return float(value) / float(maximum)

    @staticmethod
    def _candidate_sort_key(candidate: DrawPredictionCandidate):
        return (
            candidate.score,
            candidate.exact_context_hits,
            candidate.trio_context_hits,
            candidate.pair_context_hits,
            candidate.transition_hits,
            candidate.coincidence_hits,
            candidate.recent_slot_hits,
            candidate.slot_hits,
            candidate.recent_hits,
            candidate.overall_hits,
            candidate.draws_since_last_seen,
        )

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

    def _all_animal_keys(self) -> list[tuple[int, str]]:
        return [(animal_number, animal_name) for animal_number, animal_name in sorted(ANIMALITOS_MAP.items())]

    def _window_cutoffs(self, reference_local: datetime) -> dict[str, datetime]:
        return {
            "7d": reference_local - timedelta(days=7),
            "14d": reference_local - timedelta(days=14),
            "30d": reference_local - timedelta(days=30),
            "90d": reference_local - timedelta(days=90),
        }

    def _build_global_counters(
        self,
        results_desc: list[dict],
        reference_local: datetime,
        target_daypart: str,
    ) -> dict[str, Any]:
        reference_utc = reference_local.astimezone(timezone.utc)
        cutoffs = self._window_cutoffs(reference_local)
        counters = {
            "recent_7d": Counter(),
            "recent_30d": Counter(),
            "historical_90d": Counter(),
            "daypart": Counter(),
            "last_seen_draws": {},
            "unique_dates": set(),
        }

        for index, result in enumerate(results_desc):
            draw_dt = self._coerce_datetime(result["draw_datetime_utc"])
            if draw_dt > reference_utc:
                continue

            key = (result["animal_number"], get_animal_name(result["animal_number"]))
            draw_date = self._coerce_date_string(result["draw_date"])
            counters["unique_dates"].add(draw_date)

            if draw_dt >= cutoffs["90d"]:
                counters["historical_90d"][key] += 1
            if draw_dt >= cutoffs["30d"]:
                counters["recent_30d"][key] += 1
            if draw_dt >= cutoffs["7d"]:
                counters["recent_7d"][key] += 1
            if self._daypart_for_time(result["draw_time_local"]) == target_daypart:
                counters["daypart"][key] += 1

            if key not in counters["last_seen_draws"]:
                counters["last_seen_draws"][key] = index

        return counters

    def _build_window_counters(
        self,
        target_draw_time: str,
        today_results: list[dict],
        historical_days: dict[str, list[dict]],
        reference_local: datetime,
    ) -> dict[str, Counter]:
        target_weekday = reference_local.weekday()
        cutoffs = self._window_cutoffs(reference_local)
        counters = {
            "slot_recent_14d": Counter(),
            "slot_historical_90d": Counter(),
            "weekday_slot": Counter(),
            "last_transition": Counter(),
            "pair_context": Counter(),
            "trio_context": Counter(),
            "prefix_overlap": Counter(),
            "exact_prefix": Counter(),
            "same_day_repeat": Counter(),
        }

        observed_prefix_results = [item for item in today_results if item["draw_time_local"] < target_draw_time]
        observed_prefix = [item["animal_number"] for item in observed_prefix_results]
        observed_set = set(observed_prefix)
        last_one = observed_prefix[-1:] if observed_prefix else []
        last_two = observed_prefix[-2:] if len(observed_prefix) >= 2 else []
        last_three = observed_prefix[-3:] if len(observed_prefix) >= 3 else []

        for day_items in historical_days.values():
            by_time = {item["draw_time_local"]: item for item in day_items}
            target_item = by_time.get(target_draw_time)
            if not target_item:
                continue

            target_key = (
                target_item["animal_number"],
                get_animal_name(target_item["animal_number"]),
            )
            target_dt = self._coerce_datetime(target_item["draw_datetime_utc"])
            if target_dt >= cutoffs["90d"]:
                counters["slot_historical_90d"][target_key] += 1
            if target_dt >= cutoffs["14d"]:
                counters["slot_recent_14d"][target_key] += 1
            if target_dt.astimezone(reference_local.tzinfo).weekday() == target_weekday:
                counters["weekday_slot"][target_key] += 1

            historical_prefix_items = [item for item in day_items if item["draw_time_local"] < target_draw_time]
            historical_prefix_numbers = [item["animal_number"] for item in historical_prefix_items]

            if last_one and historical_prefix_numbers[-1:] == last_one:
                counters["last_transition"][target_key] += 1
            if last_two and historical_prefix_numbers[-2:] == last_two:
                counters["pair_context"][target_key] += 1
            if last_three and historical_prefix_numbers[-3:] == last_three:
                counters["trio_context"][target_key] += 1
            if observed_prefix:
                overlap = len(observed_set.intersection(historical_prefix_numbers))
                if overlap:
                    counters["prefix_overlap"][target_key] += overlap
                if historical_prefix_numbers[: len(observed_prefix)] == observed_prefix:
                    counters["exact_prefix"][target_key] += 1
                if (
                    target_item["animal_number"] in observed_set
                    and target_item["animal_number"] in historical_prefix_numbers
                ):
                    counters["same_day_repeat"][target_key] += 1

        return counters

    def _build_draw_prediction_window(
        self,
        target_draw_time: str,
        today_results: list[dict],
        historical_days: dict[str, list[dict]],
        global_counters: dict[str, Any],
        reference_local: datetime,
        top_n: int,
    ) -> DrawPredictionWindow:
        target_daypart = self._daypart_for_time(target_draw_time)
        window_counters = self._build_window_counters(
            target_draw_time=target_draw_time,
            today_results=today_results,
            historical_days=historical_days,
            reference_local=reference_local,
        )

        observed_prefix_results = [item for item in today_results if item["draw_time_local"] < target_draw_time]
        observed_prefix = [item["animal_number"] for item in observed_prefix_results]

        maxima = {
            "slot_recent_14d": max(window_counters["slot_recent_14d"].values(), default=1),
            "slot_historical_90d": max(window_counters["slot_historical_90d"].values(), default=1),
            "weekday_slot_frequency": max(window_counters["weekday_slot"].values(), default=1),
            "daypart_frequency": max(global_counters["daypart"].values(), default=1),
            "recent_frequency_7d": max(global_counters["recent_7d"].values(), default=1),
            "recent_frequency_30d": max(global_counters["recent_30d"].values(), default=1),
            "historical_frequency_90d": max(global_counters["historical_90d"].values(), default=1),
            "last_transition": max(window_counters["last_transition"].values(), default=1),
            "pair_context": max(window_counters["pair_context"].values(), default=1),
            "trio_context": max(window_counters["trio_context"].values(), default=1),
            "prefix_overlap": max(window_counters["prefix_overlap"].values(), default=1),
            "exact_prefix_match": max(window_counters["exact_prefix"].values(), default=1),
            "overdue_gap": max(global_counters["last_seen_draws"].values(), default=1) or 1,
            "same_day_repeat_pattern": max(window_counters["same_day_repeat"].values(), default=1),
        }

        candidates: list[DrawPredictionCandidate] = []
        for animal_number, animal_name in self._all_animal_keys():
            key = (animal_number, animal_name)
            score_breakdown = {
                "slot_recent_14d": round(
                    self._normalize(window_counters["slot_recent_14d"].get(key, 0), maxima["slot_recent_14d"])
                    * 0.16
                    * 100,
                    2,
                ),
                "slot_historical_90d": round(
                    self._normalize(window_counters["slot_historical_90d"].get(key, 0), maxima["slot_historical_90d"])
                    * 0.10
                    * 100,
                    2,
                ),
                "weekday_slot_frequency": round(
                    self._normalize(window_counters["weekday_slot"].get(key, 0), maxima["weekday_slot_frequency"])
                    * 0.08
                    * 100,
                    2,
                ),
                "daypart_frequency": round(
                    self._normalize(global_counters["daypart"].get(key, 0), maxima["daypart_frequency"]) * 0.06 * 100,
                    2,
                ),
                "recent_frequency_7d": round(
                    self._normalize(global_counters["recent_7d"].get(key, 0), maxima["recent_frequency_7d"]) * 0.08 * 100,
                    2,
                ),
                "recent_frequency_30d": round(
                    self._normalize(global_counters["recent_30d"].get(key, 0), maxima["recent_frequency_30d"])
                    * 0.06
                    * 100,
                    2,
                ),
                "historical_frequency_90d": round(
                    self._normalize(global_counters["historical_90d"].get(key, 0), maxima["historical_frequency_90d"])
                    * 0.04
                    * 100,
                    2,
                ),
                "last_transition": round(
                    self._normalize(window_counters["last_transition"].get(key, 0), maxima["last_transition"])
                    * 0.10
                    * 100,
                    2,
                ),
                "pair_context": round(
                    self._normalize(window_counters["pair_context"].get(key, 0), maxima["pair_context"]) * 0.08 * 100,
                    2,
                ),
                "trio_context": round(
                    self._normalize(window_counters["trio_context"].get(key, 0), maxima["trio_context"]) * 0.06 * 100,
                    2,
                ),
                "prefix_overlap": round(
                    self._normalize(window_counters["prefix_overlap"].get(key, 0), maxima["prefix_overlap"])
                    * 0.08
                    * 100,
                    2,
                ),
                "exact_prefix_match": round(
                    self._normalize(window_counters["exact_prefix"].get(key, 0), maxima["exact_prefix_match"])
                    * 0.04
                    * 100,
                    2,
                ),
                "overdue_gap": round(
                    self._normalize(global_counters["last_seen_draws"].get(key, 0), maxima["overdue_gap"]) * 0.04 * 100,
                    2,
                ),
                "same_day_repeat_pattern": round(
                    self._normalize(window_counters["same_day_repeat"].get(key, 0), maxima["same_day_repeat_pattern"])
                    * 0.02
                    * 100,
                    2,
                ),
            }
            candidates.append(
                DrawPredictionCandidate(
                    animal_number=animal_number,
                    animal_name=animal_name,
                    score=round(sum(score_breakdown.values()), 2),
                    slot_hits=window_counters["slot_historical_90d"].get(key, 0),
                    recent_slot_hits=window_counters["slot_recent_14d"].get(key, 0),
                    transition_hits=window_counters["last_transition"].get(key, 0),
                    coincidence_hits=window_counters["prefix_overlap"].get(key, 0),
                    overall_hits=global_counters["historical_90d"].get(key, 0),
                    recent_hits=global_counters["recent_30d"].get(key, 0),
                    draws_since_last_seen=global_counters["last_seen_draws"].get(key, 0),
                    weekday_slot_hits=window_counters["weekday_slot"].get(key, 0),
                    daypart_hits=global_counters["daypart"].get(key, 0),
                    pair_context_hits=window_counters["pair_context"].get(key, 0),
                    trio_context_hits=window_counters["trio_context"].get(key, 0),
                    exact_context_hits=window_counters["exact_prefix"].get(key, 0),
                    same_day_repeat_hits=window_counters["same_day_repeat"].get(key, 0),
                    score_breakdown=score_breakdown,
                )
            )

        candidates.sort(key=self._candidate_sort_key, reverse=True)
        minutes_until = None
        parsed = parse_time_local(target_draw_time)
        candidate_local = reference_local.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
        if candidate_local >= reference_local:
            minutes_until = max(int((candidate_local - reference_local).total_seconds() // 60), 0)

        return DrawPredictionWindow(
            draw_time_local=target_draw_time,
            observed_prefix=observed_prefix,
            minutes_until=minutes_until,
            daypart=target_daypart,
            candidates=candidates[: max(top_n, self.FULL_TOP_N)],
        )

    def _candidate_to_possible(self, candidate: DrawPredictionCandidate, seen_today: bool) -> PossibleResultCandidate:
        return PossibleResultCandidate(
            animal_number=candidate.animal_number,
            animal_name=candidate.animal_name,
            score=candidate.score,
            overall_hits=candidate.overall_hits,
            recent_hits=candidate.recent_hits,
            remaining_time_hits=candidate.slot_hits,
            draws_since_last_seen=candidate.draws_since_last_seen,
            seen_today=seen_today,
            weekday_slot_hits=candidate.weekday_slot_hits,
            daypart_hits=candidate.daypart_hits,
            pair_context_hits=candidate.pair_context_hits,
            trio_context_hits=candidate.trio_context_hits,
            exact_context_hits=candidate.exact_context_hits,
            same_day_repeat_hits=candidate.same_day_repeat_hits,
            score_breakdown=dict(candidate.score_breakdown),
            rank_delta=candidate.rank_delta,
        )

    def _annotate_rank_deltas(
        self,
        current_candidates: list[DrawPredictionCandidate],
        previous_candidates: list[dict] | None,
    ) -> None:
        if not previous_candidates:
            return
        previous_positions = {
            item.get("animal_number"): index
            for index, item in enumerate(previous_candidates)
            if item.get("animal_number") is not None
        }
        for index, candidate in enumerate(current_candidates):
            previous_index = previous_positions.get(candidate.animal_number)
            if previous_index is not None:
                candidate.rank_delta = previous_index - index

    def _previous_window_maps(self, previous_summary: dict | None) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
        window_map = {}
        next_map = {}
        for lottery in (previous_summary or {}).get("lotteries", []):
            lottery_name = lottery.get("canonical_lottery_name")
            next_map[lottery_name] = lottery.get("candidates", [])
            for window in lottery.get("draw_predictions", []):
                window_map[(lottery_name, window.get("draw_time_local"))] = window
        return window_map, next_map

    def _apply_change_tracking(self, summary: PossibleResultsSummary, previous_summary: dict | None) -> None:
        if previous_summary and str(previous_summary.get("reference_date")) != str(summary.reference_date):
            previous_summary = None
        previous_window_map, previous_next_map = self._previous_window_maps(previous_summary)
        change_alerts: list[str] = []

        for lottery in summary.lotteries:
            previous_next_candidates = previous_next_map.get(lottery.canonical_lottery_name)
            current_top_candidates = lottery.draw_predictions[0].candidates if lottery.draw_predictions else []
            self._annotate_rank_deltas(current_top_candidates, previous_next_candidates)

            for window in lottery.draw_predictions:
                previous_window = previous_window_map.get((lottery.canonical_lottery_name, window.draw_time_local))
                self._annotate_rank_deltas(window.candidates, previous_window.get("candidates") if previous_window else None)
                if previous_window and previous_window.get("candidates") and window.candidates:
                    previous_top = previous_window["candidates"][0]["animal_number"]
                    current_top = window.candidates[0].animal_number
                    previous_top3 = {
                        item.get("animal_number") for item in previous_window.get("candidates", [])[:3] if item.get("animal_number") is not None
                    }
                    current_top3 = {item.animal_number for item in window.candidates[:3]}
                    if previous_top != current_top or previous_top3 != current_top3:
                        window.top_candidate_changed = True
                        if previous_top != current_top:
                            window.change_summary = (
                                f"Cambia el lider de {previous_top:02d} a {current_top:02d} para {window.draw_time_local}."
                            )
                        else:
                            window.change_summary = f"Se reordeno el top 3 para {window.draw_time_local}."
                        change_alerts.append(f"{lottery.canonical_lottery_name} {window.change_summary}")

            if lottery.draw_predictions:
                observed_today = set(lottery.draw_predictions[0].observed_prefix)
                lottery.candidates = [
                    self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
                    for candidate in lottery.draw_predictions[0].candidates[: len(lottery.candidates)]
                ]
                lottery.top_3 = [
                    self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
                    for candidate in lottery.draw_predictions[0].candidates[:3]
                ]
                lottery.top_5 = [
                    self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
                    for candidate in lottery.draw_predictions[0].candidates[:5]
                ]
                lottery.top_10 = [
                    self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
                    for candidate in lottery.draw_predictions[0].candidates[:10]
                ]

        summary.change_alerts = change_alerts[:10]

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
        target_draw_times = self._get_target_draw_times(schedule, reference_local)
        today_results = [item for item in sorted_asc if self._coerce_date_string(item["draw_date"]) == reference_date_str]
        historical_days = {
            draw_date: items
            for draw_date, items in self._group_results_by_day(results).items()
            if draw_date != reference_date_str
        }
        date_span = {self._coerce_date_string(result["draw_date"]) for result in results}

        draw_predictions = []
        for target_draw_time in target_draw_times:
            global_counters = self._build_global_counters(
                results_desc=sorted_desc,
                reference_local=reference_local,
                target_daypart=self._daypart_for_time(target_draw_time),
            )
            draw_predictions.append(
                self._build_draw_prediction_window(
                    target_draw_time=target_draw_time,
                    today_results=today_results,
                    historical_days=historical_days,
                    global_counters=global_counters,
                    reference_local=reference_local,
                    top_n=top_n,
                )
            )

        next_draw = build_next_draw(schedule, reference_local) if schedule else None
        next_window = draw_predictions[0] if draw_predictions else None
        observed_today = set(next_window.observed_prefix if next_window else [])

        candidates = [
            self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
            for candidate in (next_window.candidates[:top_n] if next_window else [])
        ]
        top_3 = [
            self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
            for candidate in (next_window.candidates[:3] if next_window else [])
        ]
        top_5 = [
            self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
            for candidate in (next_window.candidates[:5] if next_window else [])
        ]
        top_10 = [
            self._candidate_to_possible(candidate, candidate.animal_number in observed_today)
            for candidate in (next_window.candidates[:10] if next_window else [])
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
            top_3=top_3,
            top_5=top_5,
            top_10=top_10,
            draw_predictions=draw_predictions,
        )

    def _build_frequency_baseline_ranking(
        self,
        history: list[dict],
        target_draw_time: str,
        reference_local: datetime,
        top_n: int,
    ) -> list[int]:
        if not history:
            return []

        sorted_desc = self._sort_results(history, reverse=True)
        cutoffs = self._window_cutoffs(reference_local)
        slot_counter = Counter()
        recent_counter = Counter()
        overall_counter = Counter()
        last_seen_draws = {}

        for index, result in enumerate(sorted_desc):
            key = result["animal_number"]
            draw_dt = self._coerce_datetime(result["draw_datetime_utc"])
            overall_counter[key] += 1
            if result["draw_time_local"] == target_draw_time:
                slot_counter[key] += 1
            if draw_dt >= cutoffs["30d"]:
                recent_counter[key] += 1
            if key not in last_seen_draws:
                last_seen_draws[key] = index

        slot_max = max(slot_counter.values(), default=1)
        recent_max = max(recent_counter.values(), default=1)
        overall_max = max(overall_counter.values(), default=1)
        overdue_max = max(last_seen_draws.values(), default=1) or 1

        ranked = []
        for animal_number, _animal_name in self._all_animal_keys():
            ranked.append(
                (
                    (
                        self._normalize(slot_counter.get(animal_number, 0), slot_max) * 0.5
                        + self._normalize(recent_counter.get(animal_number, 0), recent_max) * 0.25
                        + self._normalize(overall_counter.get(animal_number, 0), overall_max) * 0.2
                        + self._normalize(last_seen_draws.get(animal_number, 0), overdue_max) * 0.05
                    ),
                    animal_number,
                )
            )

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [animal_number for _score, animal_number in ranked[:top_n]]

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
                    next_draw=next_time,
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
        previous_summary: dict | None = None,
    ) -> PossibleResultsSummary:
        requested_top_n = top_n or settings.prediction_default_top_n
        full_top_n = max(requested_top_n, self.FULL_TOP_N)
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
                top_n=full_top_n,
            )
            if lottery_summary:
                lottery_summary.candidates = lottery_summary.candidates[:requested_top_n]
                summary_items.append(lottery_summary)
                total_history_results += lottery_summary.history_results_considered
                unique_dates.update(self._coerce_date_string(result["draw_date"]) for result in results)

        latest_backfill = db_service.get_latest_backfill_run()
        summary = PossibleResultsSummary(
            generated_at=utc_now(),
            reference_date=reference_local.date(),
            reference_time_local=reference_local.strftime("%H:%M"),
            methodology_version=self.METHODOLOGY_VERSION,
            methodology=(
                "Ranking intradia por loteria, hora, dia de semana y tramo del dia. "
                "Combina ventanas historicas de 7, 14, 30 y 90 dias con transiciones entre sorteos, "
                "contexto de parejas y trios previos, coincidencias del patron observado hoy, "
                "patrones de repeticion intradia y rezago desde la ultima aparicion."
            ),
            disclaimer="Proyeccion estadistica operativa. No garantiza aciertos ni reemplaza criterio propio.",
            baseline_methodology_version=self.BASELINE_METHODOLOGY_VERSION,
            history_days_covered=len(unique_dates),
            history_results_considered=total_history_results,
            score_components=list(SCORE_COMPONENTS),
            last_backfill_at=latest_backfill.get("completed_at") if latest_backfill else None,
            lotteries=summary_items,
        )

        if previous_summary is None:
            latest_prediction = db_service.get_latest_prediction_run()
            previous_summary = latest_prediction.get("summary") if latest_prediction else None
        self._apply_change_tracking(summary, previous_summary)
        return summary

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

        lottery_stats = defaultdict(
            lambda: {
                "total": 0,
                "top1": 0,
                "top3": 0,
                "top5": 0,
                "baseline_top1": 0,
                "baseline_top3": 0,
                "baseline_top5": 0,
            }
        )
        hour_stats = defaultdict(
            lambda: {
                "total": 0,
                "top1": 0,
                "top3": 0,
                "top5": 0,
                "baseline_top1": 0,
                "baseline_top3": 0,
                "baseline_top5": 0,
            }
        )

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
                    top_n=max(top_n, self.FULL_TOP_N),
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
                    candidate.animal_number
                    for candidate in (target_window.candidates if target_window else candidate_summary.candidates)
                ]
                baseline_ranked_numbers = self._build_frequency_baseline_ranking(
                    history=history,
                    target_draw_time=actual["draw_time_local"],
                    reference_local=reference_local,
                    top_n=max(top_n, 5),
                )

                actual_number = actual["animal_number"]
                lottery_stats[lottery_name]["total"] += 1
                hour_key = (lottery_name, actual["draw_time_local"])
                hour_stats[hour_key]["total"] += 1

                if actual_number in ranked_numbers[:1]:
                    lottery_stats[lottery_name]["top1"] += 1
                    hour_stats[hour_key]["top1"] += 1
                if actual_number in ranked_numbers[:3]:
                    lottery_stats[lottery_name]["top3"] += 1
                    hour_stats[hour_key]["top3"] += 1
                if actual_number in ranked_numbers[:5]:
                    lottery_stats[lottery_name]["top5"] += 1
                    hour_stats[hour_key]["top5"] += 1

                if actual_number in baseline_ranked_numbers[:1]:
                    lottery_stats[lottery_name]["baseline_top1"] += 1
                    hour_stats[hour_key]["baseline_top1"] += 1
                if actual_number in baseline_ranked_numbers[:3]:
                    lottery_stats[lottery_name]["baseline_top3"] += 1
                    hour_stats[hour_key]["baseline_top3"] += 1
                if actual_number in baseline_ranked_numbers[:5]:
                    lottery_stats[lottery_name]["baseline_top5"] += 1
                    hour_stats[hour_key]["baseline_top5"] += 1

        by_lottery = []
        overall_total = 0
        overall_top1 = 0
        overall_top3 = 0
        overall_top5 = 0
        baseline_overall_top1 = 0
        baseline_overall_top3 = 0
        baseline_overall_top5 = 0

        for lottery_name in selected_lotteries:
            stats = lottery_stats[lottery_name]
            total = stats["total"]
            overall_total += total
            overall_top1 += stats["top1"]
            overall_top3 += stats["top3"]
            overall_top5 += stats["top5"]
            baseline_overall_top1 += stats["baseline_top1"]
            baseline_overall_top3 += stats["baseline_top3"]
            baseline_overall_top5 += stats["baseline_top5"]
            top_3_rate = round((stats["top3"] / total) if total else 0, 4)
            baseline_top_3_rate = round((stats["baseline_top3"] / total) if total else 0, 4)
            by_lottery.append(
                BacktestingLotteryMetric(
                    lottery_name=lottery_name,
                    total_draws=total,
                    top_1_hits=stats["top1"],
                    top_3_hits=stats["top3"],
                    top_5_hits=stats["top5"],
                    top_1_rate=round((stats["top1"] / total) if total else 0, 4),
                    top_3_rate=top_3_rate,
                    top_5_rate=round((stats["top5"] / total) if total else 0, 4),
                    baseline_top_1_hits=stats["baseline_top1"],
                    baseline_top_3_hits=stats["baseline_top3"],
                    baseline_top_5_hits=stats["baseline_top5"],
                    baseline_top_1_rate=round((stats["baseline_top1"] / total) if total else 0, 4),
                    baseline_top_3_rate=baseline_top_3_rate,
                    baseline_top_5_rate=round((stats["baseline_top5"] / total) if total else 0, 4),
                    lift_top_3=round(top_3_rate - baseline_top_3_rate, 4),
                    beats_baseline=top_3_rate >= baseline_top_3_rate,
                )
            )

        by_hour = []
        for (lottery_name, draw_time_local), stats in sorted(hour_stats.items(), key=lambda item: (item[0][0], item[0][1])):
            total = stats["total"]
            top_3_rate = round((stats["top3"] / total) if total else 0, 4)
            baseline_top_3_rate = round((stats["baseline_top3"] / total) if total else 0, 4)
            by_hour.append(
                BacktestingHourMetric(
                    lottery_name=lottery_name,
                    draw_time_local=draw_time_local,
                    total_draws=total,
                    top_1_hits=stats["top1"],
                    top_3_hits=stats["top3"],
                    top_5_hits=stats["top5"],
                    top_1_rate=round((stats["top1"] / total) if total else 0, 4),
                    top_3_rate=top_3_rate,
                    top_5_rate=round((stats["top5"] / total) if total else 0, 4),
                    baseline_top_1_hits=stats["baseline_top1"],
                    baseline_top_3_hits=stats["baseline_top3"],
                    baseline_top_5_hits=stats["baseline_top5"],
                    baseline_top_1_rate=round((stats["baseline_top1"] / total) if total else 0, 4),
                    baseline_top_3_rate=baseline_top_3_rate,
                    baseline_top_5_rate=round((stats["baseline_top5"] / total) if total else 0, 4),
                    beats_baseline=top_3_rate >= baseline_top_3_rate,
                )
            )

        overall_top_3_rate = round((overall_top3 / overall_total) if overall_total else 0, 4)
        baseline_overall_top_3_rate = round((baseline_overall_top3 / overall_total) if overall_total else 0, 4)
        return BacktestingSummary(
            generated_at=utc_now(),
            days=days,
            methodology_version=self.METHODOLOGY_VERSION,
            baseline_methodology_version=self.BASELINE_METHODOLOGY_VERSION,
            overall_total_draws=overall_total,
            overall_top_1_rate=round((overall_top1 / overall_total) if overall_total else 0, 4),
            overall_top_3_rate=overall_top_3_rate,
            overall_top_5_rate=round((overall_top5 / overall_total) if overall_total else 0, 4),
            baseline_overall_top_1_rate=round((baseline_overall_top1 / overall_total) if overall_total else 0, 4),
            baseline_overall_top_3_rate=baseline_overall_top_3_rate,
            baseline_overall_top_5_rate=round((baseline_overall_top5 / overall_total) if overall_total else 0, 4),
            beats_baseline=overall_top_3_rate >= baseline_overall_top_3_rate,
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
        active_backfill_snapshot = db_service.get_analytics_snapshot("admin:backfill-status")
        scheduler_heartbeat = db_service.get_analytics_snapshot("scheduler:heartbeat") or {}
        now_local = local_now()

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

        scheduler_mode = "external+internal-fallback" if settings.use_external_scheduler else "internal"
        scheduler_last_received_at = (
            self._coerce_datetime(scheduler_heartbeat.get("last_received_at"))
            if scheduler_heartbeat.get("last_received_at")
            else None
        )
        scheduler_last_completed_at = (
            self._coerce_datetime(scheduler_heartbeat.get("last_completed_at"))
            if scheduler_heartbeat.get("last_completed_at")
            else None
        )
        scheduler_last_status = scheduler_heartbeat.get("last_status")
        scheduler_last_kind = scheduler_heartbeat.get("last_kind")
        scheduler_message = scheduler_heartbeat.get("message")

        scheduler_stale = False
        schedules = db_service.get_schedules()
        active_times = sorted({time_value for schedule in schedules for time_value in schedule.get("times", [])})
        if settings.use_external_scheduler and active_times:
            earliest_time = parse_time_local(active_times[0])
            latest_time = parse_time_local(active_times[-1])
            earliest_dt = datetime.combine(now_local.date(), earliest_time, tzinfo=now_local.tzinfo)
            latest_dt = datetime.combine(now_local.date(), latest_time, tzinfo=now_local.tzinfo) + timedelta(
                minutes=settings.scheduler_stale_threshold_minutes
            )
            if earliest_dt <= now_local <= latest_dt:
                reference_activity = scheduler_last_received_at or scheduler_last_completed_at
                if not reference_activity or utc_now() - reference_activity > timedelta(
                    minutes=settings.scheduler_stale_threshold_minutes
                ):
                    scheduler_stale = True
                    warnings.append(
                        "External scheduler heartbeat is stale; automatic refreshes may be delayed until a user session or fallback cycle wakes the service."
                    )

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
            scheduler_mode=scheduler_mode,
            scheduler_last_received_at=scheduler_last_received_at,
            scheduler_last_completed_at=scheduler_last_completed_at,
            scheduler_last_status=scheduler_last_status,
            scheduler_last_kind=scheduler_last_kind,
            scheduler_message=scheduler_message,
            scheduler_stale=scheduler_stale,
            latest_successful_run=IngestionRun.model_validate(latest_successful) if latest_successful else None,
            latest_failed_run=IngestionRun.model_validate(latest_failed) if latest_failed else None,
            latest_backfill_run=IngestionRun.model_validate(latest_backfill) if latest_backfill else None,
            latest_prediction_run=latest_prediction,
            active_backfill=(
                BackfillJobStatus.model_validate(active_backfill_snapshot)
                if active_backfill_snapshot and active_backfill_snapshot.get("status") in {"queued", "running", "finalizing"}
                else None
            ),
            total_results=db_service.count_results(),
            warnings=warnings,
        )

    def build_audit_entries(self, limit: int | None = None) -> list[AuditLogEntry]:
        limit = limit or settings.admin_audit_default_limit
        return [AuditLogEntry.model_validate(item) for item in db_service.get_audit_logs(limit=limit)]


analytics_service = AnalyticsService()
