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
    CalibrationAdjustment,
    CandidateSignal,
    DashboardOverview,
    DrawPredictionCandidate,
    DrawPredictionWindow,
    EnjauladosResponse,
    IngestionRun,
    LotteryOverviewCard,
    LotteryPossibleResults,
    ModelHealthBandMetric,
    ModelHealthSummary,
    ModelSegmentHealth,
    PossibleResultCandidate,
    PossibleResultsSummary,
    PredictionReviewHourMetric,
    PredictionReviewLotteryMetric,
    PredictionReviewSignalMetric,
    PredictionReviewSummary,
    PredictionReviewWindow,
    QualityLotteryRecord,
    QualityReportResponse,
    ScoreComponent,
    SystemStatusResponse,
    StrategiesResponse,
    StrategyConsensusAnimal,
    StrategyPerformance,
    TrendBucket,
    get_animal_name,
)
from app.services.database import db_service
from app.services.external_signals import external_signals_service
from app.services.prediction_models import (
    EXTERNAL_COMPONENT_KEYS,
    INTERNAL_COMPONENT_KEYS,
    build_ensemble_score,
    build_external_raw_prior,
    build_rule_score,
    build_segment_key,
    compute_window_stability,
    make_feature_payload,
    normalize_external_priors,
    normalize_window_values,
    predict_segment_probabilities,
    stable_probability_band,
    train_segment_model,
)
from app.services.schedule import build_next_draw, expected_draws_by_now, local_now, parse_time_local, utc_now
from app.services.telegram import telegram_service


PREVIOUS_COMPONENT_WEIGHTS = {
    "slot_recent_14d": 0.14,
    "slot_historical_90d": 0.09,
    "slot_last4_occurrences": 0.08,
    "weekday_slot_frequency": 0.08,
    "daypart_frequency": 0.05,
    "recent_frequency_7d": 0.07,
    "recent_frequency_30d": 0.05,
    "historical_frequency_90d": 0.03,
    "last_transition": 0.09,
    "pair_context": 0.06,
    "trio_context": 0.04,
    "prefix_overlap": 0.05,
    "exact_prefix_match": 0.02,
    "cross_lottery_overlap": 0.05,
    "cross_lottery_exact": 0.02,
    "overdue_gap": 0.06,
    "same_day_repeat_pattern": 0.02,
    "strategy_consensus": 0.0,
    "strategy_adaptive": 0.0,
    "enjaulado_pressure": 0.0,
}

COMPONENT_LABELS = {
    "slot_recent_14d": "Frecuencia reciente por hora (14d)",
    "slot_historical_90d": "Frecuencia historica por hora (90d)",
    "slot_last4_occurrences": "Presencia en las ultimas 4 apariciones de esa hora",
    "weekday_slot_frequency": "Coincidencia por dia de semana y hora",
    "daypart_frequency": "Frecuencia por tramo del dia",
    "recent_frequency_7d": "Frecuencia global reciente (7d)",
    "recent_frequency_30d": "Frecuencia global reciente (30d)",
    "historical_frequency_90d": "Frecuencia global historica (90d)",
    "last_transition": "Transicion desde el ultimo resultado",
    "pair_context": "Pareja previa coincidente",
    "trio_context": "Trio previo coincidente",
    "prefix_overlap": "Coincidencias con el patron del dia",
    "exact_prefix_match": "Ruta exacta del dia",
    "cross_lottery_overlap": "Coincidencia con el contexto de otras loterias",
    "cross_lottery_exact": "Contexto exacto de otras loterias",
    "overdue_gap": "Rezago desde ultima aparicion",
    "same_day_repeat_pattern": "Patron de repeticion intradia",
    "strategy_consensus": "Consenso entre estrategias externas",
    "strategy_adaptive": "Peso adaptativo de estrategias segun aciertos del dia",
    "enjaulado_pressure": "Presion por animal enjaulado",
}

COMPONENT_WEIGHTS = {
    "slot_recent_14d": 0.12,
    "slot_historical_90d": 0.08,
    "slot_last4_occurrences": 0.07,
    "weekday_slot_frequency": 0.07,
    "daypart_frequency": 0.04,
    "recent_frequency_7d": 0.06,
    "recent_frequency_30d": 0.04,
    "historical_frequency_90d": 0.03,
    "last_transition": 0.08,
    "pair_context": 0.05,
    "trio_context": 0.03,
    "prefix_overlap": 0.04,
    "exact_prefix_match": 0.02,
    "cross_lottery_overlap": 0.04,
    "cross_lottery_exact": 0.01,
    "overdue_gap": 0.05,
    "same_day_repeat_pattern": 0.02,
    "strategy_consensus": 0.08,
    "strategy_adaptive": 0.05,
    "enjaulado_pressure": 0.02,
}

WEIGHT_ADJUSTMENT_RATIONALES = {
    "slot_recent_14d": "Se refuerza la recurrencia reciente por hora para favorecer ventanas con repeticion estable.",
    "slot_historical_90d": "Sube ligeramente para dar mas estabilidad historica cuando el contexto intradia es debil.",
    "slot_last4_occurrences": "Baja para reducir sobreajuste a las ultimas pocas apariciones de la misma hora.",
    "weekday_slot_frequency": "Se refuerza porque la medicion por dia/hora viene mostrando mejor estabilidad que el contexto exacto.",
    "daypart_frequency": "Aumenta para amortiguar horas flojas con una senal mas estable por tramo del dia.",
    "recent_frequency_7d": "Sube para darle mas reaccion al comportamiento reciente sin depender solo del dia actual.",
    "last_transition": "Se reduce ligeramente para no sobrerreaccionar a una sola transicion previa.",
    "pair_context": "Se modera para equilibrar contexto y frecuencia estable.",
    "trio_context": "Se modera porque es mas fragil y menos frecuente que la pareja previa.",
    "prefix_overlap": "Baja para evitar que el patron observado hoy domine demasiado temprano.",
    "exact_prefix_match": "Se reduce porque la ruta exacta del dia es una senal muy escasa y volatil.",
    "cross_lottery_overlap": "Se reduce por el underperformance observado en ventanas de Internacional al usar demasiado contexto cruzado.",
    "cross_lottery_exact": "Se reduce mas por ser una senal muy especifica y propensa a sobreajuste.",
    "overdue_gap": "Se equilibra con enjaulados para no empujar demasiado un mismo rezago por dos vias distintas.",
    "same_day_repeat_pattern": "Sube un poco para capturar repeticiones intradia cuando ya hay jornada observada.",
    "strategy_consensus": "Nueva senal de consenso externo para capturar animales repetidos entre varias estrategias del dia.",
    "strategy_adaptive": "Nueva senal adaptativa que refuerza estrategias que vienen acertando mejor en la jornada actual.",
    "enjaulado_pressure": "Nueva senal ligera para incorporar el rezago operativo de los animalitos enjaulados por loteria.",
}

SCORE_COMPONENTS = [
    ScoreComponent(key=key, label=COMPONENT_LABELS[key], weight=weight)
    for key, weight in COMPONENT_WEIGHTS.items()
]


class AnalyticsService:
    METHODOLOGY_VERSION = "ops-hybrid-ranking-v8"
    ENSEMBLE_VERSION = "hybrid-ensemble-v1"
    BASELINE_METHODOLOGY_VERSION = "frequency-baseline-v1"
    MINIMUM_BACKTEST_HISTORY = 10
    FULL_TOP_N = 10
    SLOT_CONTEXT_DEPTH = 4
    MARKET_CONTEXT_DEPTH = 6
    MODEL_LOOKBACK_DAYS = 90
    MINIMUM_MODEL_EXAMPLES = 300
    SEGMENT_KEYS = [
        "lotto-activo-hourly",
        "la-granjita-hourly",
        "internacional-hourly",
        "internacional-halfhour",
    ]

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
    def _day_item_sort_key(item: dict) -> tuple[str, str]:
        return item["draw_time_local"], item["canonical_lottery_name"]

    @staticmethod
    def _candidate_sort_key(candidate: DrawPredictionCandidate):
        return (
            candidate.ensemble_score or candidate.score,
            candidate.model_probability,
            candidate.rule_score,
            candidate.strategy_weighted_hits,
            candidate.strategy_hits,
            candidate.enjaulado_days_without_hit,
            candidate.cross_lottery_exact_hits,
            candidate.cross_lottery_hits,
            candidate.last4_slot_hits,
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

    @staticmethod
    def _signal_intensity(contribution: float) -> str:
        if contribution >= 10:
            return "muy-alta"
        if contribution >= 6:
            return "alta"
        if contribution >= 3:
            return "media"
        return "baja"

    def _component_raw_value(self, candidate: DrawPredictionCandidate | PossibleResultCandidate, key: str) -> float | None:
        mapping = {
            "slot_recent_14d": "recent_slot_hits",
            "slot_historical_90d": "slot_hits",
            "slot_last4_occurrences": "last4_slot_hits",
            "weekday_slot_frequency": "weekday_slot_hits",
            "daypart_frequency": "daypart_hits",
            "recent_frequency_7d": "recent_hits",
            "recent_frequency_30d": "recent_hits",
            "historical_frequency_90d": "overall_hits",
            "last_transition": "transition_hits",
            "pair_context": "pair_context_hits",
            "trio_context": "trio_context_hits",
            "prefix_overlap": "coincidence_hits",
            "exact_prefix_match": "exact_context_hits",
            "cross_lottery_overlap": "cross_lottery_hits",
            "cross_lottery_exact": "cross_lottery_exact_hits",
            "overdue_gap": "draws_since_last_seen",
            "same_day_repeat_pattern": "same_day_repeat_hits",
            "strategy_consensus": "strategy_hits",
            "strategy_adaptive": "strategy_weighted_hits",
            "enjaulado_pressure": "enjaulado_days_without_hit",
        }
        attr_name = mapping.get(key)
        if not attr_name:
            return None

        if hasattr(candidate, attr_name):
            raw_value = getattr(candidate, attr_name)
            if raw_value is not None:
                return float(raw_value)

        if key == "slot_historical_90d" and hasattr(candidate, "remaining_time_hits"):
            raw_value = getattr(candidate, "remaining_time_hits")
            if raw_value is not None:
                return float(raw_value)

        return None

    def _top_signal_details(
        self,
        candidate: DrawPredictionCandidate | PossibleResultCandidate,
        *,
        limit: int = 3,
    ) -> list[CandidateSignal]:
        ranked = sorted(
            candidate.score_breakdown.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        signals = []
        for key, contribution in ranked:
            if contribution <= 0:
                continue
            signals.append(
                CandidateSignal(
                    key=key,
                    label=COMPONENT_LABELS.get(key, key),
                    contribution=round(contribution, 2),
                    weight=COMPONENT_WEIGHTS.get(key, 0),
                    raw_value=self._component_raw_value(candidate, key),
                    intensity=self._signal_intensity(contribution),
                )
            )
            if len(signals) >= limit:
                break
        return signals

    def _summarize_candidate_movement(
        self,
        candidate: DrawPredictionCandidate | PossibleResultCandidate,
        *,
        previous_candidate: dict | None = None,
    ) -> str | None:
        signals = candidate.strongest_signals or self._top_signal_details(candidate)
        signal_labels = [signal.label.lower() for signal in signals[:2]]
        reasons = ", ".join(signal_labels)

        if previous_candidate is None:
            if not reasons:
                return None
            return f"Entra con fuerza por {reasons}."

        movement_prefix = None
        if candidate.rank_delta:
            if candidate.rank_delta > 0:
                movement_prefix = f"Sube {candidate.rank_delta} puesto{'s' if candidate.rank_delta != 1 else ''}"
            elif candidate.rank_delta < 0:
                movement_prefix = f"Baja {abs(candidate.rank_delta)} puesto{'s' if abs(candidate.rank_delta) != 1 else ''}"
        elif candidate.score_delta:
            if candidate.score_delta > 0:
                movement_prefix = "Gana puntuacion"
            elif candidate.score_delta < 0:
                movement_prefix = "Pierde puntuacion"

        if not movement_prefix and not reasons:
            return None
        if movement_prefix and reasons:
            return f"{movement_prefix} por {reasons}."
        return movement_prefix

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

    def _build_recent_slot_counter(
        self,
        results_desc: list[dict],
        target_draw_time: str,
        reference_local: datetime,
    ) -> Counter:
        reference_utc = reference_local.astimezone(timezone.utc)
        counter = Counter()
        slot_hits = 0

        for result in results_desc:
            draw_dt = self._coerce_datetime(result["draw_datetime_utc"])
            if draw_dt > reference_utc or result["draw_time_local"] != target_draw_time:
                continue

            key = (result["animal_number"], get_animal_name(result["animal_number"]))
            counter[key] += 1
            slot_hits += 1
            if slot_hits >= self.SLOT_CONTEXT_DEPTH:
                break

        return counter

    def _build_market_prefix(
        self,
        market_day_items: list[dict],
        *,
        target_lottery_name: str,
        target_draw_time: str,
    ) -> list[tuple[str, int]]:
        prefix = []
        for item in sorted(market_day_items, key=self._day_item_sort_key):
            if item["canonical_lottery_name"] == target_lottery_name:
                continue
            if item["draw_time_local"] >= target_draw_time:
                continue
            prefix.append((item["canonical_lottery_name"], item["animal_number"]))
        if len(prefix) <= self.MARKET_CONTEXT_DEPTH:
            return prefix
        return prefix[-self.MARKET_CONTEXT_DEPTH :]

    def _build_window_counters(
        self,
        lottery_name: str,
        target_draw_time: str,
        today_results: list[dict],
        historical_days: dict[str, list[dict]],
        results_desc: list[dict],
        market_today_results: list[dict],
        market_historical_days: dict[str, list[dict]],
        reference_local: datetime,
    ) -> dict[str, Counter]:
        target_weekday = reference_local.weekday()
        cutoffs = self._window_cutoffs(reference_local)
        counters = {
            "slot_recent_14d": Counter(),
            "slot_historical_90d": Counter(),
            "slot_last4": self._build_recent_slot_counter(
                results_desc=results_desc,
                target_draw_time=target_draw_time,
                reference_local=reference_local,
            ),
            "weekday_slot": Counter(),
            "last_transition": Counter(),
            "pair_context": Counter(),
            "trio_context": Counter(),
            "prefix_overlap": Counter(),
            "exact_prefix": Counter(),
            "same_day_repeat": Counter(),
            "cross_overlap": Counter(),
            "cross_exact": Counter(),
        }

        observed_prefix_results = [item for item in today_results if item["draw_time_local"] < target_draw_time]
        observed_prefix = [item["animal_number"] for item in observed_prefix_results]
        observed_set = set(observed_prefix)
        last_one = observed_prefix[-1:] if observed_prefix else []
        last_two = observed_prefix[-2:] if len(observed_prefix) >= 2 else []
        last_three = observed_prefix[-3:] if len(observed_prefix) >= 3 else []
        observed_market_prefix = self._build_market_prefix(
            market_today_results,
            target_lottery_name=lottery_name,
            target_draw_time=target_draw_time,
        )
        observed_market_set = set(observed_market_prefix)

        for draw_date, day_items in historical_days.items():
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

            if observed_market_prefix:
                market_day_items = market_historical_days.get(draw_date, [])
                historical_market_prefix = self._build_market_prefix(
                    market_day_items,
                    target_lottery_name=lottery_name,
                    target_draw_time=target_draw_time,
                )
                overlap = len(observed_market_set.intersection(historical_market_prefix))
                if overlap:
                    counters["cross_overlap"][target_key] += overlap
                if historical_market_prefix[-len(observed_market_prefix) :] == observed_market_prefix:
                    counters["cross_exact"][target_key] += 1

        return counters

    def _window_is_weak_sample(
        self,
        *,
        historical_days: dict[str, list[dict]],
        window_counters: dict[str, Counter],
        target_draw_time: str,
        lottery_name: str,
    ) -> bool:
        comparable_days = 0
        for day_items in historical_days.values():
            if any(item["draw_time_local"] == target_draw_time for item in day_items):
                comparable_days += 1
        slot_depth = sum(window_counters["slot_historical_90d"].values())
        if lottery_name == "Lotto Activo Internacional" and target_draw_time.endswith(":30"):
            return comparable_days < 18 or slot_depth < 18
        return comparable_days < 24 or slot_depth < 24

    def _apply_hybrid_scores(
        self,
        *,
        candidates: list[DrawPredictionCandidate],
        lottery_name: str,
        target_draw_time: str,
        reference_local: datetime,
        daypart: str,
        weak_sample: bool,
    ) -> tuple[str, dict | None, float, str]:
        if not candidates:
            segment_key = build_segment_key(lottery_name, target_draw_time)
            return segment_key, None, 0.0, "baja"

        segment_key = build_segment_key(lottery_name, target_draw_time)
        champion_model = db_service.get_champion_model(segment_key)
        rule_scores = [build_rule_score(candidate.score_breakdown) for candidate in candidates]
        external_raw_priors = [build_external_raw_prior(candidate.score_breakdown) for candidate in candidates]
        normalized_rule_scores = normalize_window_values(rule_scores)
        normalized_external_priors = normalize_external_priors(external_raw_priors, cap=1.0)
        weekday = reference_local.weekday()
        feature_rows = [
            make_feature_payload(
                candidate,
                rule_score=rule_score,
                external_prior=external_prior,
                draw_time_local=target_draw_time,
                weekday=weekday,
                daypart=daypart,
            )
            for candidate, rule_score, external_prior in zip(
                candidates,
                rule_scores,
                normalized_external_priors,
                strict=False,
            )
        ]
        probabilities = predict_segment_probabilities(champion_model, feature_rows)

        for candidate, rule_score, external_prior, normalized_rule_score, model_probability in zip(
            candidates,
            rule_scores,
            normalized_external_priors,
            normalized_rule_scores,
            probabilities,
            strict=False,
        ):
            candidate.rule_score = round(rule_score, 2)
            candidate.external_prior = round(external_prior, 4)
            candidate.model_probability = round(model_probability, 4)
            candidate.ensemble_score = build_ensemble_score(
                model_probability=model_probability,
                normalized_rule_score=normalized_rule_score,
                external_prior=external_prior,
            )
            candidate.segment_key = segment_key
            candidate.champion_model_key = champion_model.get("model_key") if champion_model else None
            candidate.weak_sample = weak_sample
            candidate.score = round(candidate.ensemble_score * 100, 2)

        candidates.sort(key=self._candidate_sort_key, reverse=True)
        comparison_index = min(4, len(candidates) - 1)
        ensemble_gap = max(candidates[0].ensemble_score - candidates[comparison_index].ensemble_score, 0)
        stability_score = compute_window_stability(
            current_top_numbers=[candidate.animal_number for candidate in candidates[:3]],
            previous_top_numbers=None,
            ensemble_gap=ensemble_gap,
            weak_sample=weak_sample,
        )
        confidence_band = stable_probability_band(
            candidates[0].model_probability if candidates else 0.0,
            stability_score,
            weak_sample,
        )
        for candidate in candidates:
            candidate.stability_score = stability_score
            candidate.confidence_band = stable_probability_band(
                candidate.model_probability,
                stability_score,
                weak_sample,
            )
        return segment_key, champion_model, stability_score, confidence_band

    def _build_draw_prediction_window(
        self,
        lottery_name: str,
        target_draw_time: str,
        today_results: list[dict],
        historical_days: dict[str, list[dict]],
        results_desc: list[dict],
        market_today_results: list[dict],
        market_historical_days: dict[str, list[dict]],
        global_counters: dict[str, Any],
        strategy_context: dict[str, Any],
        reference_local: datetime,
        top_n: int,
    ) -> DrawPredictionWindow:
        target_daypart = self._daypart_for_time(target_draw_time)
        window_counters = self._build_window_counters(
            lottery_name=lottery_name,
            target_draw_time=target_draw_time,
            today_results=today_results,
            historical_days=historical_days,
            results_desc=results_desc,
            market_today_results=market_today_results,
            market_historical_days=market_historical_days,
            reference_local=reference_local,
        )

        observed_prefix_results = [item for item in today_results if item["draw_time_local"] < target_draw_time]
        observed_prefix = [item["animal_number"] for item in observed_prefix_results]

        maxima = {
            "slot_recent_14d": max(window_counters["slot_recent_14d"].values(), default=1),
            "slot_historical_90d": max(window_counters["slot_historical_90d"].values(), default=1),
            "slot_last4_occurrences": max(window_counters["slot_last4"].values(), default=1),
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
            "cross_lottery_overlap": max(window_counters["cross_overlap"].values(), default=1),
            "cross_lottery_exact": max(window_counters["cross_exact"].values(), default=1),
            "overdue_gap": max(global_counters["last_seen_draws"].values(), default=1) or 1,
            "same_day_repeat_pattern": max(window_counters["same_day_repeat"].values(), default=1),
            "strategy_consensus": max(strategy_context.get("consensus_counts", {}).values(), default=1),
            "strategy_adaptive": max(strategy_context.get("adaptive_scores", {}).values(), default=1),
            "enjaulado_pressure": strategy_context.get("enjaulado_max", 1) or 1,
        }
        weak_sample = self._window_is_weak_sample(
            historical_days=historical_days,
            window_counters=window_counters,
            target_draw_time=target_draw_time,
            lottery_name=lottery_name,
        )

        candidates: list[DrawPredictionCandidate] = []
        for animal_number, animal_name in self._all_animal_keys():
            key = (animal_number, animal_name)
            strategy_hits = strategy_context.get("consensus_counts", {}).get(key, 0)
            strategy_weighted_hits = strategy_context.get("adaptive_scores", {}).get(key, 0)
            enjaulado_days = strategy_context.get("enjaulados_by_lottery", {}).get(lottery_name, {}).get(key, 0)
            score_breakdown = {
                "slot_recent_14d": round(
                    self._normalize(window_counters["slot_recent_14d"].get(key, 0), maxima["slot_recent_14d"])
                    * COMPONENT_WEIGHTS["slot_recent_14d"]
                    * 100,
                    2,
                ),
                "slot_historical_90d": round(
                    self._normalize(window_counters["slot_historical_90d"].get(key, 0), maxima["slot_historical_90d"])
                    * COMPONENT_WEIGHTS["slot_historical_90d"]
                    * 100,
                    2,
                ),
                "slot_last4_occurrences": round(
                    self._normalize(window_counters["slot_last4"].get(key, 0), maxima["slot_last4_occurrences"])
                    * COMPONENT_WEIGHTS["slot_last4_occurrences"]
                    * 100,
                    2,
                ),
                "weekday_slot_frequency": round(
                    self._normalize(window_counters["weekday_slot"].get(key, 0), maxima["weekday_slot_frequency"])
                    * COMPONENT_WEIGHTS["weekday_slot_frequency"]
                    * 100,
                    2,
                ),
                "daypart_frequency": round(
                    self._normalize(global_counters["daypart"].get(key, 0), maxima["daypart_frequency"])
                    * COMPONENT_WEIGHTS["daypart_frequency"]
                    * 100,
                    2,
                ),
                "recent_frequency_7d": round(
                    self._normalize(global_counters["recent_7d"].get(key, 0), maxima["recent_frequency_7d"])
                    * COMPONENT_WEIGHTS["recent_frequency_7d"]
                    * 100,
                    2,
                ),
                "recent_frequency_30d": round(
                    self._normalize(global_counters["recent_30d"].get(key, 0), maxima["recent_frequency_30d"])
                    * COMPONENT_WEIGHTS["recent_frequency_30d"]
                    * 100,
                    2,
                ),
                "historical_frequency_90d": round(
                    self._normalize(global_counters["historical_90d"].get(key, 0), maxima["historical_frequency_90d"])
                    * COMPONENT_WEIGHTS["historical_frequency_90d"]
                    * 100,
                    2,
                ),
                "last_transition": round(
                    self._normalize(window_counters["last_transition"].get(key, 0), maxima["last_transition"])
                    * COMPONENT_WEIGHTS["last_transition"]
                    * 100,
                    2,
                ),
                "pair_context": round(
                    self._normalize(window_counters["pair_context"].get(key, 0), maxima["pair_context"])
                    * COMPONENT_WEIGHTS["pair_context"]
                    * 100,
                    2,
                ),
                "trio_context": round(
                    self._normalize(window_counters["trio_context"].get(key, 0), maxima["trio_context"])
                    * COMPONENT_WEIGHTS["trio_context"]
                    * 100,
                    2,
                ),
                "prefix_overlap": round(
                    self._normalize(window_counters["prefix_overlap"].get(key, 0), maxima["prefix_overlap"])
                    * COMPONENT_WEIGHTS["prefix_overlap"]
                    * 100,
                    2,
                ),
                "exact_prefix_match": round(
                    self._normalize(window_counters["exact_prefix"].get(key, 0), maxima["exact_prefix_match"])
                    * COMPONENT_WEIGHTS["exact_prefix_match"]
                    * 100,
                    2,
                ),
                "cross_lottery_overlap": round(
                    self._normalize(window_counters["cross_overlap"].get(key, 0), maxima["cross_lottery_overlap"])
                    * COMPONENT_WEIGHTS["cross_lottery_overlap"]
                    * 100,
                    2,
                ),
                "cross_lottery_exact": round(
                    self._normalize(window_counters["cross_exact"].get(key, 0), maxima["cross_lottery_exact"])
                    * COMPONENT_WEIGHTS["cross_lottery_exact"]
                    * 100,
                    2,
                ),
                "overdue_gap": round(
                    self._normalize(global_counters["last_seen_draws"].get(key, 0), maxima["overdue_gap"])
                    * COMPONENT_WEIGHTS["overdue_gap"]
                    * 100,
                    2,
                ),
                "same_day_repeat_pattern": round(
                    self._normalize(window_counters["same_day_repeat"].get(key, 0), maxima["same_day_repeat_pattern"])
                    * COMPONENT_WEIGHTS["same_day_repeat_pattern"]
                    * 100,
                    2,
                ),
                "strategy_consensus": round(
                    self._normalize(strategy_hits, maxima["strategy_consensus"])
                    * COMPONENT_WEIGHTS["strategy_consensus"]
                    * 100,
                    2,
                ),
                "strategy_adaptive": round(
                    self._normalize(strategy_weighted_hits, maxima["strategy_adaptive"])
                    * COMPONENT_WEIGHTS["strategy_adaptive"]
                    * 100,
                    2,
                ),
                "enjaulado_pressure": round(
                    self._normalize(enjaulado_days, maxima["enjaulado_pressure"])
                    * COMPONENT_WEIGHTS["enjaulado_pressure"]
                    * 100,
                    2,
                ),
            }
            candidate = DrawPredictionCandidate(
                animal_number=animal_number,
                animal_name=animal_name,
                score=round(sum(score_breakdown.values()), 2),
                slot_hits=window_counters["slot_historical_90d"].get(key, 0),
                recent_slot_hits=window_counters["slot_recent_14d"].get(key, 0),
                last4_slot_hits=window_counters["slot_last4"].get(key, 0),
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
                cross_lottery_hits=window_counters["cross_overlap"].get(key, 0),
                cross_lottery_exact_hits=window_counters["cross_exact"].get(key, 0),
                strategy_hits=strategy_hits,
                strategy_weighted_hits=round(strategy_weighted_hits, 2),
                enjaulado_days_without_hit=enjaulado_days,
                score_breakdown=score_breakdown,
            )
            candidate.strongest_signals = self._top_signal_details(candidate)
            candidates.append(candidate)

        segment_key, champion_model, stability_score, confidence_band = self._apply_hybrid_scores(
            candidates=candidates,
            lottery_name=lottery_name,
            target_draw_time=target_draw_time,
            reference_local=reference_local,
            daypart=target_daypart,
            weak_sample=weak_sample,
        )
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
            segment_key=segment_key,
            stability_score=stability_score,
            confidence_band=confidence_band,
            champion_model_key=champion_model.get("model_key") if champion_model else None,
            weak_sample=weak_sample,
            candidates=candidates,
        )

    def _candidate_to_possible(self, candidate: DrawPredictionCandidate, seen_today: bool) -> PossibleResultCandidate:
        return PossibleResultCandidate(
            animal_number=candidate.animal_number,
            animal_name=candidate.animal_name,
            score=candidate.score,
            rule_score=candidate.rule_score,
            model_probability=candidate.model_probability,
            external_prior=candidate.external_prior,
            ensemble_score=candidate.ensemble_score,
            confidence_band=candidate.confidence_band,
            segment_key=candidate.segment_key,
            stability_score=candidate.stability_score,
            champion_model_key=candidate.champion_model_key,
            weak_sample=candidate.weak_sample,
            overall_hits=candidate.overall_hits,
            recent_hits=candidate.recent_hits,
            remaining_time_hits=candidate.slot_hits,
            last4_slot_hits=candidate.last4_slot_hits,
            draws_since_last_seen=candidate.draws_since_last_seen,
            seen_today=seen_today,
            weekday_slot_hits=candidate.weekday_slot_hits,
            daypart_hits=candidate.daypart_hits,
            pair_context_hits=candidate.pair_context_hits,
            trio_context_hits=candidate.trio_context_hits,
            exact_context_hits=candidate.exact_context_hits,
            same_day_repeat_hits=candidate.same_day_repeat_hits,
            cross_lottery_hits=candidate.cross_lottery_hits,
            cross_lottery_exact_hits=candidate.cross_lottery_exact_hits,
            strategy_hits=candidate.strategy_hits,
            strategy_weighted_hits=candidate.strategy_weighted_hits,
            enjaulado_days_without_hit=candidate.enjaulado_days_without_hit,
            score_breakdown=dict(candidate.score_breakdown),
            strongest_signals=list(candidate.strongest_signals),
            rank_delta=candidate.rank_delta,
            previous_rank=candidate.previous_rank,
            score_delta=candidate.score_delta,
            movement_summary=candidate.movement_summary,
        )

    def _annotate_rank_deltas(
        self,
        current_candidates: list[DrawPredictionCandidate],
        previous_candidates: list[dict] | None,
    ) -> None:
        has_previous = bool(previous_candidates)
        previous_positions = {}
        previous_map = {}
        for index, item in enumerate(previous_candidates or []):
            animal_number = item.get("animal_number")
            if animal_number is None:
                continue
            previous_positions[animal_number] = index
            previous_map[animal_number] = item

        for index, candidate in enumerate(current_candidates):
            candidate.strongest_signals = self._top_signal_details(candidate)
            previous_index = previous_positions.get(candidate.animal_number)
            previous_candidate = previous_map.get(candidate.animal_number)
            if previous_index is not None:
                candidate.rank_delta = previous_index - index
                candidate.previous_rank = previous_index + 1
            previous_score = previous_candidate.get("score") if previous_candidate else None
            if previous_score is not None:
                candidate.score_delta = round(candidate.score - float(previous_score), 2)
            candidate.movement_summary = (
                self._summarize_candidate_movement(candidate, previous_candidate=previous_candidate)
                if has_previous
                else None
            )

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
                comparison_index = min(4, len(window.candidates) - 1) if window.candidates else 0
                ensemble_gap = (
                    max(window.candidates[0].ensemble_score - window.candidates[comparison_index].ensemble_score, 0)
                    if window.candidates
                    else 0
                )
                stability_score = compute_window_stability(
                    current_top_numbers=[candidate.animal_number for candidate in window.candidates[:3]],
                    previous_top_numbers=[
                        int(item.get("animal_number"))
                        for item in (previous_window.get("candidates") if previous_window else [])[:3]
                        if item.get("animal_number") is not None
                    ],
                    ensemble_gap=ensemble_gap,
                    weak_sample=window.weak_sample,
                )
                window.stability_score = stability_score
                window.confidence_band = stable_probability_band(
                    window.candidates[0].model_probability if window.candidates else 0.0,
                    stability_score,
                    window.weak_sample,
                )
                for candidate in window.candidates:
                    candidate.stability_score = stability_score
                    candidate.confidence_band = stable_probability_band(
                        candidate.model_probability,
                        stability_score,
                        candidate.weak_sample,
                    )
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

    def _build_weight_adjustments(self) -> list[CalibrationAdjustment]:
        adjustments = []
        for key, current_weight in COMPONENT_WEIGHTS.items():
            previous_weight = PREVIOUS_COMPONENT_WEIGHTS.get(key, current_weight)
            delta = round(current_weight - previous_weight, 4)
            if abs(delta) < 0.005:
                continue
            adjustments.append(
                CalibrationAdjustment(
                    key=key,
                    label=COMPONENT_LABELS.get(key, key),
                    previous_weight=previous_weight,
                    current_weight=current_weight,
                    delta=delta,
                    rationale=WEIGHT_ADJUSTMENT_RATIONALES.get(
                        key,
                        "Ajuste aplicado para balancear estabilidad y contexto intradia.",
                    ),
                )
            )
        adjustments.sort(key=lambda item: abs(item.delta), reverse=True)
        return adjustments

    def _build_calibration_payload(
        self,
        *,
        by_lottery: list[BacktestingLotteryMetric],
        by_hour: list[BacktestingHourMetric],
        overall_top_3_rate: float,
        baseline_overall_top_3_rate: float,
    ) -> dict[str, Any]:
        strongest_lotteries = sorted(
            by_lottery,
            key=lambda item: (item.lift_top_3, item.top_3_rate, item.total_draws),
            reverse=True,
        )[:3]
        weakest_lotteries = sorted(
            by_lottery,
            key=lambda item: (item.lift_top_3, item.top_3_rate, item.total_draws),
        )[:3]
        strongest_hours = sorted(
            by_hour,
            key=lambda item: ((item.top_3_rate - item.baseline_top_3_rate), item.top_3_rate, item.total_draws),
            reverse=True,
        )[:5]
        weakest_hours = sorted(
            by_hour,
            key=lambda item: ((item.top_3_rate - item.baseline_top_3_rate), item.top_3_rate, item.total_draws),
        )[:5]

        strongest_lottery = strongest_lotteries[0] if strongest_lotteries else None
        weakest_lottery = weakest_lotteries[0] if weakest_lotteries else None
        strongest_hour = strongest_hours[0] if strongest_hours else None
        weakest_hour = weakest_hours[0] if weakest_hours else None
        overall_lift = round(overall_top_3_rate - baseline_overall_top_3_rate, 4)
        status_label = "supera" if overall_lift >= 0 else "todavia no supera"
        summary = (
            f"El ranking {status_label} el baseline simple en Top 3 por "
            f"{overall_lift * 100:+.1f} puntos sobre la ventana medida."
        )

        notes = [
            (
                f"Mejor loteria actual: {strongest_lottery.lottery_name} con Top 3 "
                f"{strongest_lottery.top_3_rate * 100:.1f}% y lift {strongest_lottery.lift_top_3 * 100:+.1f} pts."
            )
            if strongest_lottery
            else "No hay suficiente data para identificar una loteria fuerte."
        ]
        if weakest_lottery:
            notes.append(
                f"Loteria a vigilar: {weakest_lottery.lottery_name} con Top 3 {weakest_lottery.top_3_rate * 100:.1f}% "
                f"y lift {weakest_lottery.lift_top_3 * 100:+.1f} pts."
            )
        if strongest_hour:
            notes.append(
                f"Ventana mas estable: {strongest_hour.lottery_name} {strongest_hour.draw_time_local} "
                f"({strongest_hour.top_3_rate * 100:.1f}% Top 3)."
            )
        if weakest_hour:
            notes.append(
                f"Ventana mas debil: {weakest_hour.lottery_name} {weakest_hour.draw_time_local} "
                f"({weakest_hour.top_3_rate * 100:.1f}% Top 3 vs {weakest_hour.baseline_top_3_rate * 100:.1f}% baseline)."
            )
        if overall_lift < 0:
            notes.append(
                "La recalibracion actual prioriza estabilidad por hora y dia; conviene seguir observando si reduce el gap negativo."
            )
        else:
            notes.append("La recalibracion ya esta empujando las ventanas donde el contexto reciente supera a la frecuencia simple.")

        return {
            "calibration_summary": summary,
            "calibration_notes": notes,
            "weight_adjustments": self._build_weight_adjustments(),
            "strongest_lotteries": strongest_lotteries,
            "weakest_lotteries": weakest_lotteries,
            "strongest_hours": strongest_hours,
            "weakest_hours": weakest_hours,
        }

    def _build_candidates_for_reference(
        self,
        lottery_name: str,
        results: list[dict],
        schedule: dict,
        reference_local: datetime,
        top_n: int,
        market_results: list[dict] | None = None,
    ) -> LotteryPossibleResults | None:
        if not results:
            return None

        market_results = market_results or results
        sorted_desc = self._sort_results(results, reverse=True)
        sorted_asc = list(reversed(sorted_desc))
        market_sorted_asc = self._sort_results(market_results)
        reference_date_str = reference_local.date().isoformat()
        target_draw_times = self._get_target_draw_times(schedule, reference_local)
        today_results = [item for item in sorted_asc if self._coerce_date_string(item["draw_date"]) == reference_date_str]
        market_today_results = [
            item for item in market_sorted_asc if self._coerce_date_string(item["draw_date"]) == reference_date_str
        ]
        historical_days = {
            draw_date: items
            for draw_date, items in self._group_results_by_day(results).items()
            if draw_date != reference_date_str
        }
        market_historical_days = {
            draw_date: items
            for draw_date, items in self._group_results_by_day(market_results).items()
            if draw_date != reference_date_str
        }
        date_span = {self._coerce_date_string(result["draw_date"]) for result in results}
        strategy_context = self._build_external_strategy_context(reference_local)

        draw_predictions = []
        for target_draw_time in target_draw_times:
            global_counters = self._build_global_counters(
                results_desc=sorted_desc,
                reference_local=reference_local,
                target_daypart=self._daypart_for_time(target_draw_time),
            )
            draw_predictions.append(
                self._build_draw_prediction_window(
                    lottery_name=lottery_name,
                    target_draw_time=target_draw_time,
                    today_results=today_results,
                    historical_days=historical_days,
                    results_desc=sorted_desc,
                    market_today_results=market_today_results,
                    market_historical_days=market_historical_days,
                    global_counters=global_counters,
                    strategy_context=strategy_context,
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

    def _build_training_examples(
        self,
        *,
        days: int | None = None,
        lotteries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        days = days or self.MODEL_LOOKBACK_DAYS
        selected_lotteries = self._normalize_lotteries(lotteries)
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        now_local = local_now()
        start_date = (now_local.date() - timedelta(days=days - 1)).isoformat()
        end_date = now_local.date().isoformat()
        results_by_lottery = {
            lottery_name: db_service.get_results(
                canonical_lottery_name=lottery_name,
                start_date=start_date,
                end_date=end_date,
                limit=None,
            )
            for lottery_name in selected_lotteries
        }
        market_ordered = self._sort_results(
            [item for lottery_name in selected_lotteries for item in results_by_lottery.get(lottery_name, [])]
        )
        examples: list[dict[str, Any]] = []

        for lottery_name in selected_lotteries:
            items = results_by_lottery.get(lottery_name, [])
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
                actual_dt = self._coerce_datetime(actual["draw_datetime_utc"])
                market_history = [
                    item for item in market_ordered if self._coerce_datetime(item["draw_datetime_utc"]) < actual_dt
                ]
                candidate_summary = self._build_candidates_for_reference(
                    lottery_name=lottery_name,
                    results=history,
                    schedule=schedule,
                    reference_local=reference_local,
                    top_n=self.FULL_TOP_N,
                    market_results=market_history,
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
                if not target_window:
                    continue

                window_key = f"{draw_date_value.isoformat()}:{lottery_name}:{actual['draw_time_local']}"
                daypart = target_window.daypart or self._daypart_for_time(actual["draw_time_local"])
                weekday = reference_local.weekday()
                for candidate in target_window.candidates:
                    feature_payload = make_feature_payload(
                        candidate,
                        rule_score=candidate.rule_score,
                        external_prior=candidate.external_prior,
                        draw_time_local=actual["draw_time_local"],
                        weekday=weekday,
                        daypart=daypart,
                    )
                    examples.append(
                        {
                            "example_key": (
                                f"{draw_date_value.isoformat()}:{lottery_name}:{actual['draw_time_local']}:"
                                f"{candidate.animal_number:02d}"
                            ),
                            "segment_key": candidate.segment_key or build_segment_key(lottery_name, actual["draw_time_local"]),
                            "canonical_lottery_name": lottery_name,
                            "draw_date": draw_date_value,
                            "draw_time_local": actual["draw_time_local"],
                            "animal_number": candidate.animal_number,
                            "label_hit": candidate.animal_number == int(actual["animal_number"]),
                            "methodology_version": self.METHODOLOGY_VERSION,
                            "generated_at": utc_now(),
                            "features": feature_payload,
                            "metadata": {
                                "window_key": window_key,
                                "actual_animal_number": int(actual["animal_number"]),
                                "actual_animal_name": actual["animal_name"],
                                "champion_model_key": candidate.champion_model_key,
                                "confidence_band": candidate.confidence_band,
                                "stability_score": candidate.stability_score,
                                "weak_sample": candidate.weak_sample,
                            },
                        }
                    )

        return examples

    def _promotion_gate_notes(
        self,
        *,
        segment_key: str,
        candidate_metrics: dict[str, Any],
        champion_metrics: dict[str, Any] | None,
    ) -> tuple[bool, list[str]]:
        if not champion_metrics:
            return True, ["Primer champion disponible para el segmento."]

        candidate_top5 = float(candidate_metrics.get("validation_top_5_rate", 0.0))
        candidate_top3 = float(candidate_metrics.get("validation_top_3_rate", 0.0))
        champion_top5 = float(champion_metrics.get("validation_top_5_rate", 0.0))
        champion_top3 = float(champion_metrics.get("validation_top_3_rate", 0.0))
        gain_top5 = round(candidate_top5 - champion_top5, 4)
        delta_top3 = round(candidate_top3 - champion_top3, 4)
        notes = [
            f"Top 5 candidato {candidate_top5 * 100:.1f}% vs champion {champion_top5 * 100:.1f}% (delta {gain_top5 * 100:+.1f} pts).",
            f"Top 3 candidato {candidate_top3 * 100:.1f}% vs champion {champion_top3 * 100:.1f}% (delta {delta_top3 * 100:+.1f} pts).",
        ]
        if gain_top5 < 0.02:
            notes.append("No se promociona porque no supera el umbral minimo de +2 pts en Top 5.")
            return False, notes
        if delta_top3 < -0.01:
            notes.append("No se promociona porque Top 3 cae mas de 1 punto absoluto.")
            return False, notes
        if segment_key.startswith("internacional") and gain_top5 <= 0 and delta_top3 <= 0:
            notes.append("No se promociona porque el segmento internacional no mejora ni Top 5 ni Top 3.")
            return False, notes
        notes.append("El candidato cumple las compuertas minimas de promocion.")
        return True, notes

    def train_models_and_promote(self, days: int | None = None) -> dict[str, dict[str, Any]]:
        examples = self._build_training_examples(days=days or self.MODEL_LOOKBACK_DAYS)
        db_service.save_model_training_examples(examples)
        grouped_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for example in examples:
            grouped_examples[example["segment_key"]].append(example)

        training_summary: dict[str, dict[str, Any]] = {}
        trained_at = utc_now()
        for segment_key in self.SEGMENT_KEYS:
            segment_examples = grouped_examples.get(segment_key, [])
            if len(segment_examples) < self.MINIMUM_MODEL_EXAMPLES:
                training_summary[segment_key] = {
                    "status": "insufficient-data",
                    "examples": len(segment_examples),
                    "promoted": False,
                }
                continue

            trained = train_segment_model(segment_key, segment_examples)
            if not trained:
                training_summary[segment_key] = {
                    "status": "training-failed",
                    "examples": len(segment_examples),
                    "promoted": False,
                }
                continue

            champion = db_service.get_champion_model(segment_key)
            champion_metrics = (champion or {}).get("validation_metrics") or {}
            should_promote, notes = self._promotion_gate_notes(
                segment_key=segment_key,
                candidate_metrics=trained.get("validation_metrics", {}),
                champion_metrics=champion_metrics if champion else None,
            )
            model_payload = {
                "model_key": f"{self.ENSEMBLE_VERSION}:{segment_key}:{trained_at.strftime('%Y%m%d%H%M%S')}",
                "segment_key": segment_key,
                "status": "champion" if should_promote else "candidate",
                "trained_at": trained_at,
                "training_start_date": trained.get("training_start_date"),
                "training_end_date": trained.get("training_end_date"),
                "ensemble_weights": {"model_probability": 0.6, "rule_score": 0.3, "external_prior": 0.1},
                "validation_metrics": trained.get("validation_metrics", {}),
                "calibration_method": trained.get("calibration_method"),
                "artifact": trained.get("artifact", {}),
                "notes": notes,
            }

            if should_promote and champion:
                archived = dict(champion)
                archived["status"] = "archived"
                archived["notes"] = list((archived.get("notes") or [])) + [
                    f"Archivado al promover {model_payload['model_key']}."
                ]
                db_service.save_model_version(archived)

            db_service.save_model_version(model_payload)
            training_summary[segment_key] = {
                "status": model_payload["status"],
                "examples": len(segment_examples),
                "promoted": should_promote,
                "model_key": model_payload["model_key"],
                "validation_metrics": model_payload["validation_metrics"],
            }

        return training_summary

    def ensure_champion_models(self) -> dict[str, dict[str, Any]]:
        missing_segments = [segment_key for segment_key in self.SEGMENT_KEYS if not db_service.get_champion_model(segment_key)]
        if not missing_segments:
            return {
                segment_key: {
                    "status": "ready",
                    "model_key": (db_service.get_champion_model(segment_key) or {}).get("model_key"),
                }
                for segment_key in self.SEGMENT_KEYS
            }
        return self.train_models_and_promote()

    def _confidence_bands_from_reviews(self, segment_key: str, reviews: list[dict[str, Any]]) -> list[ModelHealthBandMetric]:
        rows = []
        grouped = defaultdict(list)
        for review in reviews:
            grouped[review.get("confidence_band") or "baja"].append(review)
        for band in ("alta", "media", "baja"):
            items = grouped.get(band, [])
            total = len(items)
            rows.append(
                ModelHealthBandMetric(
                    confidence_band=band,
                    evaluated_draws=total,
                    hit_top_1_rate=round(sum(1 for item in items if item.get("hit_top_1")) / total, 4) if total else 0,
                    hit_top_3_rate=round(sum(1 for item in items if item.get("hit_top_3")) / total, 4) if total else 0,
                    hit_top_5_rate=round(sum(1 for item in items if item.get("hit_top_5")) / total, 4) if total else 0,
                )
            )
        return rows

    def build_model_health_summary(self) -> ModelHealthSummary:
        start_date = (local_now().date() - timedelta(days=30)).isoformat()
        review_rows = db_service.get_prediction_window_reviews(start_date=start_date, limit=None)
        segments = []
        for segment_key in self.SEGMENT_KEYS:
            champion = db_service.get_champion_model(segment_key)
            segment_reviews = [row for row in review_rows if row.get("segment_key") == segment_key]
            confidence_bands = self._confidence_bands_from_reviews(segment_key, segment_reviews)
            if champion:
                metrics = champion.get("validation_metrics", {})
                notes = list(champion.get("notes") or [])
                segments.append(
                    ModelSegmentHealth(
                        segment_key=segment_key,
                        status=champion.get("status", "champion"),
                        champion_model_key=champion.get("model_key"),
                        trained_at=champion.get("trained_at"),
                        training_start_date=champion.get("training_start_date"),
                        training_end_date=champion.get("training_end_date"),
                        validation_top_1_rate=metrics.get("validation_top_1_rate", 0),
                        validation_top_3_rate=metrics.get("validation_top_3_rate", 0),
                        validation_top_5_rate=metrics.get("validation_top_5_rate", 0),
                        baseline_top_3_rate=metrics.get("baseline_top_3_rate", 0),
                        baseline_top_5_rate=metrics.get("baseline_top_5_rate", 0),
                        calibration_method=champion.get("calibration_method"),
                        confidence_bands=confidence_bands,
                        notes=notes[:4],
                    )
                )
            else:
                segments.append(
                    ModelSegmentHealth(
                        segment_key=segment_key,
                        status="missing",
                        confidence_bands=confidence_bands,
                        notes=["Aun no hay champion persistido para este segmento."],
                    )
                )

        notes = [
            "La capa ML reordena con HistGradientBoosting por segmento y calibracion temporal.",
            "Las bandas de confianza se calculan contra reviews reales del ultimo mes cuando existen.",
        ]
        return ModelHealthSummary(
            generated_at=utc_now(),
            ensemble_version=self.ENSEMBLE_VERSION,
            segments=segments,
            notes=notes,
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
        self.ensure_daily_external_snapshots(target_date=reference_local.date(), force_refresh=False)
        self.ensure_champion_models()
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        selected_lotteries = self._normalize_lotteries(lotteries)
        champion_versions = {
            segment_key: (db_service.get_champion_model(segment_key) or {}).get("model_key")
            for segment_key in self.SEGMENT_KEYS
        }
        results_by_lottery = {
            lottery_name: db_service.get_results(canonical_lottery_name=lottery_name, limit=None)
            for lottery_name in selected_lotteries
        }
        market_results = [
            result
            for lottery_name in selected_lotteries
            for result in results_by_lottery.get(lottery_name, [])
        ]
        summary_items = []
        unique_dates = set()
        total_history_results = 0

        for lottery_name in selected_lotteries:
            results = results_by_lottery.get(lottery_name, [])
            schedule = schedules.get(lottery_name, {"times": []})
            lottery_summary = self._build_candidates_for_reference(
                lottery_name=lottery_name,
                results=results,
                schedule=schedule,
                reference_local=reference_local,
                top_n=full_top_n,
                market_results=market_results,
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
            ensemble_version=self.ENSEMBLE_VERSION,
            methodology=(
                "Motor hibrido explicable por segmento. El score final combina una capa estadistica interpretable "
                "(frecuencia por hora, dia, transiciones, contexto y rezago), una probabilidad supervisada calibrada "
                "con HistGradientBoosting por segmento y un prior externo controlado para estrategias/enjaulados. "
                "Internacional separa ventanas :00 y :30 para evitar mezclar patrones incompatibles."
            ),
            disclaimer="Proyeccion estadistica operativa. No garantiza aciertos ni reemplaza criterio propio.",
            baseline_methodology_version=self.BASELINE_METHODOLOGY_VERSION,
            history_days_covered=len(unique_dates),
            history_results_considered=total_history_results,
            model_version_by_segment=champion_versions,
            score_components=list(SCORE_COMPONENTS),
            last_backfill_at=latest_backfill.get("completed_at") if latest_backfill else None,
            lotteries=summary_items,
        )

        if previous_summary is None:
            latest_prediction = db_service.get_latest_prediction_run()
            previous_summary = latest_prediction.get("summary") if latest_prediction else None
        self._apply_change_tracking(summary, previous_summary)
        all_windows = [window for lottery in summary.lotteries for window in lottery.draw_predictions]
        stability_counts = Counter(window.confidence_band for window in all_windows)
        summary.prediction_stability = {
            "high_confidence_windows": stability_counts.get("alta", 0),
            "medium_confidence_windows": stability_counts.get("media", 0),
            "low_confidence_windows": stability_counts.get("baja", 0),
            "average_stability_score": round(
                sum(window.stability_score for window in all_windows) / len(all_windows),
                4,
            )
            if all_windows
            else 0,
        }
        return summary

    def build_backtesting_summary(
        self,
        days: int | None = None,
        top_n: int | None = None,
        lotteries: list[str] | None = None,
    ) -> BacktestingSummary:
        days = days or settings.analytics_default_days
        top_n = max(top_n or settings.prediction_default_top_n, 5)
        self.ensure_champion_models()
        selected_lotteries = self._normalize_lotteries(lotteries)
        schedules = {item["canonical_lottery_name"]: item for item in db_service.get_schedules()}
        now_local = local_now()
        start_date = (now_local.date() - timedelta(days=days - 1)).isoformat()
        end_date = now_local.date().isoformat()
        results_by_lottery = {
            lottery_name: db_service.get_results(
                canonical_lottery_name=lottery_name,
                start_date=start_date,
                end_date=end_date,
                limit=None,
            )
            for lottery_name in selected_lotteries
        }
        market_ordered = self._sort_results(
            [item for lottery_name in selected_lotteries for item in results_by_lottery.get(lottery_name, [])]
        )

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
            items = results_by_lottery.get(lottery_name, [])
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
                actual_dt = self._coerce_datetime(actual["draw_datetime_utc"])
                market_history = [
                    item for item in market_ordered if self._coerce_datetime(item["draw_datetime_utc"]) < actual_dt
                ]
                candidate_summary = self._build_candidates_for_reference(
                    lottery_name=lottery_name,
                    results=history,
                    schedule=schedule,
                    reference_local=reference_local,
                    top_n=max(top_n, self.FULL_TOP_N),
                    market_results=market_history,
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
        calibration_payload = self._build_calibration_payload(
            by_lottery=by_lottery,
            by_hour=by_hour,
            overall_top_3_rate=overall_top_3_rate,
            baseline_overall_top_3_rate=baseline_overall_top_3_rate,
        )
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
            calibration_summary=calibration_payload["calibration_summary"],
            calibration_notes=calibration_payload["calibration_notes"],
            weight_adjustments=calibration_payload["weight_adjustments"],
            strongest_lotteries=calibration_payload["strongest_lotteries"],
            weakest_lotteries=calibration_payload["weakest_lotteries"],
            strongest_hours=calibration_payload["strongest_hours"],
            weakest_hours=calibration_payload["weakest_hours"],
        )

    def build_backtesting_placeholder_summary(
        self,
        days: int | None = None,
        lotteries: list[str] | None = None,
    ) -> BacktestingSummary:
        days = days or settings.analytics_default_days
        selected_lotteries = self._normalize_lotteries(lotteries)
        return BacktestingSummary(
            generated_at=utc_now(),
            days=days,
            methodology_version=self.METHODOLOGY_VERSION,
            baseline_methodology_version=self.BASELINE_METHODOLOGY_VERSION,
            overall_total_draws=0,
            overall_top_1_rate=0,
            overall_top_3_rate=0,
            overall_top_5_rate=0,
            baseline_overall_top_1_rate=0,
            baseline_overall_top_3_rate=0,
            baseline_overall_top_5_rate=0,
            beats_baseline=False,
            by_lottery=[
                BacktestingLotteryMetric(
                    lottery_name=lottery_name,
                    total_draws=0,
                    top_1_hits=0,
                    top_3_hits=0,
                    top_5_hits=0,
                    top_1_rate=0,
                    top_3_rate=0,
                    top_5_rate=0,
                    baseline_top_1_hits=0,
                    baseline_top_3_hits=0,
                    baseline_top_5_hits=0,
                    baseline_top_1_rate=0,
                    baseline_top_3_rate=0,
                    baseline_top_5_rate=0,
                    lift_top_3=0,
                    beats_baseline=False,
                )
                for lottery_name in selected_lotteries
            ],
            by_hour=[],
            calibration_summary="El snapshot de backtesting se esta recalculando en segundo plano.",
            calibration_notes=[
                "La vista ya puede usarse mientras el backtesting termina de regenerarse.",
                "En cuanto el snapshot quede listo, la pagina mostrara lift, fortalezas y horas debiles reales.",
            ],
            weight_adjustments=self._build_weight_adjustments(),
            strongest_lotteries=[],
            weakest_lotteries=[],
            strongest_hours=[],
            weakest_hours=[],
        )

    def _daily_external_snapshot_key(self, prefix: str, target_date: date | None = None) -> str:
        target_date = target_date or local_now().date()
        return f"{prefix}:{target_date.isoformat()}"

    def _frozen_external_snapshot_key(self, prefix: str, target_date: date | None = None) -> str:
        target_date = target_date or local_now().date()
        return f"frozen-{prefix}:{target_date.isoformat()}"

    def ensure_daily_external_snapshots(self, target_date: date | None = None, force_refresh: bool = False) -> None:
        target_date = target_date or local_now().date()
        if target_date != local_now().date() and not force_refresh:
            return
        enjaulados = self._load_enjaulados_data(force_refresh=force_refresh, target_date=target_date)
        strategies = self._load_strategy_sources(force_refresh=force_refresh, target_date=target_date)
        db_service.save_analytics_snapshot(
            snapshot_key=self._frozen_external_snapshot_key("external-enjaulados", target_date),
            snapshot=enjaulados.model_dump(),
        )
        db_service.save_analytics_snapshot(
            snapshot_key=self._frozen_external_snapshot_key("external-strategies", target_date),
            snapshot={"generated_at": utc_now(), "sources": strategies},
        )

    def _load_enjaulados_data(
        self,
        force_refresh: bool = False,
        target_date: date | None = None,
        frozen: bool = False,
    ) -> EnjauladosResponse:
        target_date = target_date or local_now().date()
        snapshot_key = (
            self._frozen_external_snapshot_key("external-enjaulados", target_date)
            if frozen
            else self._daily_external_snapshot_key("external-enjaulados", target_date)
        )
        if not force_refresh:
            snapshot = db_service.get_analytics_snapshot(snapshot_key)
            if snapshot:
                return EnjauladosResponse.model_validate(snapshot)
            if frozen and target_date != local_now().date():
                return EnjauladosResponse(generated_at=utc_now(), lotteries=[])

        try:
            payload = external_signals_service.get_enjaulados(force_refresh=force_refresh)
            if not frozen:
                db_service.save_analytics_snapshot(snapshot_key=snapshot_key, snapshot=payload.model_dump())
            return payload
        except Exception:
            latest_snapshot = db_service.get_latest_analytics_snapshot(
                "frozen-external-enjaulados:" if frozen else "external-enjaulados:"
            )
            if latest_snapshot:
                return EnjauladosResponse.model_validate(latest_snapshot)
            return EnjauladosResponse(generated_at=utc_now(), lotteries=[])

    def _load_strategy_sources(
        self,
        force_refresh: bool = False,
        target_date: date | None = None,
        frozen: bool = False,
    ) -> list:
        target_date = target_date or local_now().date()
        snapshot_key = (
            self._frozen_external_snapshot_key("external-strategies", target_date)
            if frozen
            else self._daily_external_snapshot_key("external-strategies", target_date)
        )
        if not force_refresh:
            snapshot = db_service.get_analytics_snapshot(snapshot_key)
            if snapshot:
                return snapshot.get("sources", [])
            if frozen and target_date != local_now().date():
                return []

        try:
            payload = external_signals_service.get_strategy_sources(force_refresh=force_refresh)
            if not frozen:
                db_service.save_analytics_snapshot(
                    snapshot_key=snapshot_key,
                    snapshot={
                        "generated_at": utc_now(),
                        "sources": [item.model_dump() for item in payload],
                    },
                )
            return [item.model_dump() for item in payload]
        except Exception:
            latest_snapshot = db_service.get_latest_analytics_snapshot(
                "frozen-external-strategies:" if frozen else "external-strategies:"
            )
            if latest_snapshot:
                return latest_snapshot.get("sources", [])
            return []

    def build_enjaulados_summary(self, force_refresh: bool = False) -> EnjauladosResponse:
        today = local_now().date()
        self.ensure_daily_external_snapshots(target_date=today, force_refresh=force_refresh)
        return self._load_enjaulados_data(force_refresh=False, target_date=today, frozen=not force_refresh)

    def refresh_external_signal_snapshots(self) -> None:
        target_date = local_now().date()
        enjaulados = external_signals_service.get_enjaulados(force_refresh=True)
        strategies = external_signals_service.get_strategy_sources(force_refresh=True)
        enjaulados_payload = enjaulados.model_dump()
        strategies_payload = {"generated_at": utc_now(), "sources": [item.model_dump() for item in strategies]}
        db_service.save_analytics_snapshot(
            snapshot_key=self._daily_external_snapshot_key("external-enjaulados", target_date),
            snapshot=enjaulados_payload,
        )
        db_service.save_analytics_snapshot(
            snapshot_key=self._daily_external_snapshot_key("external-strategies", target_date),
            snapshot=strategies_payload,
        )
        db_service.save_analytics_snapshot(
            snapshot_key=self._frozen_external_snapshot_key("external-enjaulados", target_date),
            snapshot=enjaulados_payload,
        )
        db_service.save_analytics_snapshot(
            snapshot_key=self._frozen_external_snapshot_key("external-strategies", target_date),
            snapshot=strategies_payload,
        )

    def _coerce_local_draw_datetime(self, draw_date_value, draw_time_local: str) -> datetime:
        draw_date = draw_date_value
        if isinstance(draw_date_value, str):
            draw_date = date.fromisoformat(draw_date_value)
        return datetime.combine(draw_date, parse_time_local(draw_time_local), tzinfo=local_now().tzinfo)

    def build_today_prediction_review(self, draw_date: date | None = None) -> PredictionReviewSummary:
        draw_date = draw_date or local_now().date()
        draw_date_key = draw_date.isoformat()
        results = db_service.get_results(start_date=draw_date_key, end_date=draw_date_key, limit=None)
        target_results = [
            item for item in results if item.get("canonical_lottery_name") in PRIMARY_LOTTERIES and ":" in item.get("draw_time_local", "")
        ]
        prediction_runs = db_service.get_prediction_runs(limit=500)

        valid_runs = []
        for run in prediction_runs:
            summary = run.get("summary") or {}
            generated_at = run.get("generated_at")
            if isinstance(generated_at, str):
                generated_at = self._coerce_datetime(generated_at)
            if not generated_at or summary.get("reference_date") not in {None, draw_date_key}:
                continue
            valid_runs.append((generated_at, run))
        valid_runs.sort(key=lambda item: item[0])

        windows = []
        persisted_reviews = []
        totals = {"evaluated": 0, "top1": 0, "top3": 0, "top5": 0}
        by_lottery = {}
        by_hour = {}
        by_signal = {}

        for result in sorted(target_results, key=lambda item: self._coerce_datetime(item["draw_datetime_utc"])):
            lottery_name = result["canonical_lottery_name"]
            draw_time_local = result["draw_time_local"]
            actual_number = int(result["animal_number"])
            draw_datetime_utc = self._coerce_datetime(result["draw_datetime_utc"])
            matched_window = None
            matched_run = None

            for generated_at, run in valid_runs:
                if generated_at > draw_datetime_utc:
                    continue
                summary = run.get("summary") or {}
                for lottery in summary.get("lotteries", []):
                    if lottery.get("canonical_lottery_name") != lottery_name:
                        continue
                    for window in lottery.get("draw_predictions", []):
                        if window.get("draw_time_local") == draw_time_local:
                            matched_window = window
                            matched_run = run

            if not matched_window:
                windows.append(
                    PredictionReviewWindow(
                        canonical_lottery_name=lottery_name,
                        draw_date=draw_date,
                        draw_time_local=draw_time_local,
                        actual_animal_number=actual_number,
                        actual_animal_name=result["animal_name"],
                        prediction_available=False,
                    )
                )
                continue

            candidate_rows = matched_window.get("candidates", [])
            top_numbers = [int(candidate.get("animal_number")) for candidate in candidate_rows]
            top_1 = top_numbers[:1]
            top_3 = top_numbers[:3]
            top_5 = top_numbers[:5]
            hit_top_1 = actual_number in top_1
            hit_top_3 = actual_number in top_3
            hit_top_5 = actual_number in top_5
            actual_rank = top_numbers.index(actual_number) + 1 if actual_number in top_numbers else None
            predicted_top_candidate = candidate_rows[0] if candidate_rows else {}
            predicted_top_1_number = predicted_top_candidate.get("animal_number")
            predicted_top_1_name = predicted_top_candidate.get("animal_name")
            champion_model_key = predicted_top_candidate.get("champion_model_key") or matched_window.get("champion_model_key")
            confidence_band = predicted_top_candidate.get("confidence_band") or matched_window.get("confidence_band")
            stability_score = predicted_top_candidate.get("stability_score") or matched_window.get("stability_score")
            segment_key = predicted_top_candidate.get("segment_key") or matched_window.get("segment_key")
            lead_signal_key = None
            lead_signal_label = None
            strongest_signals = predicted_top_candidate.get("strongest_signals") or []
            if strongest_signals:
                lead_signal_key = strongest_signals[0].get("key")
                lead_signal_label = strongest_signals[0].get("label") or COMPONENT_LABELS.get(
                    lead_signal_key,
                    lead_signal_key,
                )
            elif predicted_top_candidate.get("score_breakdown"):
                lead_signal_key = max(
                    predicted_top_candidate.get("score_breakdown", {}).items(),
                    key=lambda item: item[1],
                )[0]
                lead_signal_label = COMPONENT_LABELS.get(lead_signal_key, lead_signal_key)

            window_row = PredictionReviewWindow(
                canonical_lottery_name=lottery_name,
                draw_date=draw_date,
                draw_time_local=draw_time_local,
                segment_key=segment_key,
                actual_animal_number=actual_number,
                actual_animal_name=result["animal_name"],
                predicted_at=matched_run.get("generated_at"),
                prediction_delivery_status=matched_run.get("delivery_status"),
                champion_model_key=champion_model_key,
                confidence_band=confidence_band,
                stability_score=stability_score,
                predicted_top_1_number=predicted_top_1_number,
                predicted_top_1_name=predicted_top_1_name,
                lead_signal_key=lead_signal_key,
                lead_signal_label=lead_signal_label,
                top_1=top_1,
                top_3=top_3,
                top_5=top_5,
                hit_top_1=hit_top_1,
                hit_top_3=hit_top_3,
                hit_top_5=hit_top_5,
                actual_rank=actual_rank,
                prediction_available=True,
            )
            windows.append(window_row)
            persisted_reviews.append(
                {
                    "review_key": f"{draw_date.isoformat()}:{lottery_name}:{draw_time_local}",
                    "segment_key": segment_key or build_segment_key(lottery_name, draw_time_local),
                    "canonical_lottery_name": lottery_name,
                    "draw_date": draw_date,
                    "draw_time_local": draw_time_local,
                    "actual_animal_number": actual_number,
                    "actual_animal_name": result["animal_name"],
                    "predicted_at": matched_run.get("generated_at"),
                    "model_key": champion_model_key,
                    "ensemble_version": self.ENSEMBLE_VERSION,
                    "lead_signal_key": lead_signal_key,
                    "confidence_band": confidence_band,
                    "stability_score": stability_score,
                    "hit_top_1": hit_top_1,
                    "hit_top_3": hit_top_3,
                    "hit_top_5": hit_top_5,
                    "payload": {
                        "predicted_top_1_number": predicted_top_1_number,
                        "predicted_top_1_name": predicted_top_1_name,
                        "top_1": top_1,
                        "top_3": top_3,
                        "top_5": top_5,
                        "actual_rank": actual_rank,
                    },
                }
            )

            totals["evaluated"] += 1
            totals["top1"] += int(hit_top_1)
            totals["top3"] += int(hit_top_3)
            totals["top5"] += int(hit_top_5)

            lottery_metric = by_lottery.setdefault(
                lottery_name,
                {"evaluated": 0, "top1": 0, "top3": 0, "top5": 0},
            )
            lottery_metric["evaluated"] += 1
            lottery_metric["top1"] += int(hit_top_1)
            lottery_metric["top3"] += int(hit_top_3)
            lottery_metric["top5"] += int(hit_top_5)

            hour_metric = by_hour.setdefault(
                (lottery_name, draw_time_local),
                {"evaluated": 0, "top1": 0, "top3": 0, "top5": 0},
            )
            hour_metric["evaluated"] += 1
            hour_metric["top1"] += int(hit_top_1)
            hour_metric["top3"] += int(hit_top_3)
            hour_metric["top5"] += int(hit_top_5)

            if lead_signal_key:
                signal_metric = by_signal.setdefault(
                    lead_signal_key,
                    {
                        "label": lead_signal_label or COMPONENT_LABELS.get(lead_signal_key, lead_signal_key),
                        "evaluated": 0,
                        "top1": 0,
                        "top3": 0,
                        "top5": 0,
                    },
                )
                signal_metric["evaluated"] += 1
                signal_metric["top1"] += int(hit_top_1)
                signal_metric["top3"] += int(hit_top_3)
                signal_metric["top5"] += int(hit_top_5)

        lottery_rows = []
        for lottery_name in PRIMARY_LOTTERIES:
            metric = by_lottery.get(lottery_name, {"evaluated": 0, "top1": 0, "top3": 0, "top5": 0})
            evaluated = metric["evaluated"]
            lottery_rows.append(
                PredictionReviewLotteryMetric(
                    canonical_lottery_name=lottery_name,
                    evaluated_draws=evaluated,
                    hit_top_1=metric["top1"],
                    hit_top_3=metric["top3"],
                    hit_top_5=metric["top5"],
                    hit_top_1_rate=round(metric["top1"] / evaluated, 4) if evaluated else 0,
                    hit_top_3_rate=round(metric["top3"] / evaluated, 4) if evaluated else 0,
                    hit_top_5_rate=round(metric["top5"] / evaluated, 4) if evaluated else 0,
                )
            )

        hour_rows = []
        for (lottery_name, draw_time_local), metric in sorted(by_hour.items(), key=lambda item: (item[0][0], item[0][1])):
            evaluated = metric["evaluated"]
            hour_rows.append(
                PredictionReviewHourMetric(
                    canonical_lottery_name=lottery_name,
                    draw_time_local=draw_time_local,
                    evaluated_draws=evaluated,
                    hit_top_1=metric["top1"],
                    hit_top_3=metric["top3"],
                    hit_top_5=metric["top5"],
                    hit_top_1_rate=round(metric["top1"] / evaluated, 4) if evaluated else 0,
                    hit_top_3_rate=round(metric["top3"] / evaluated, 4) if evaluated else 0,
                    hit_top_5_rate=round(metric["top5"] / evaluated, 4) if evaluated else 0,
                )
            )

        signal_rows = []
        for signal_key, metric in sorted(by_signal.items(), key=lambda item: (item[1]["top3"], item[1]["evaluated"]), reverse=True):
            evaluated = metric["evaluated"]
            signal_rows.append(
                PredictionReviewSignalMetric(
                    signal_key=signal_key,
                    signal_label=metric["label"],
                    evaluated_draws=evaluated,
                    hit_top_1=metric["top1"],
                    hit_top_3=metric["top3"],
                    hit_top_5=metric["top5"],
                    hit_top_1_rate=round(metric["top1"] / evaluated, 4) if evaluated else 0,
                    hit_top_3_rate=round(metric["top3"] / evaluated, 4) if evaluated else 0,
                    hit_top_5_rate=round(metric["top5"] / evaluated, 4) if evaluated else 0,
                )
            )

        strongest_hours = sorted(
            [row for row in hour_rows if row.evaluated_draws > 0],
            key=lambda item: (item.hit_top_3_rate, item.hit_top_5_rate, item.evaluated_draws),
            reverse=True,
        )[:4]
        weakest_hours = sorted(
            [row for row in hour_rows if row.evaluated_draws > 0],
            key=lambda item: (item.hit_top_3_rate, item.hit_top_5_rate, -item.evaluated_draws),
        )[:4]
        strongest_signals = sorted(
            [row for row in signal_rows if row.evaluated_draws > 0],
            key=lambda item: (item.hit_top_3_rate, item.hit_top_5_rate, item.evaluated_draws),
            reverse=True,
        )[:4]
        weakest_signals = sorted(
            [row for row in signal_rows if row.evaluated_draws > 0],
            key=lambda item: (item.hit_top_3_rate, item.hit_top_5_rate, -item.evaluated_draws),
        )[:4]

        notes = []
        missing_predictions = len([window for window in windows if not window.prediction_available])
        if missing_predictions:
            notes.append(
                f"{missing_predictions} sorteos del dia no pudieron cruzarse con una corrida previa guardada del sistema."
            )
        if totals["evaluated"]:
            notes.append(
                f"Resumen operativo: Top 5 acerto {totals['top5']} de {totals['evaluated']} sorteos evaluados."
            )
        if strongest_signals:
            notes.append(
                f"La senal lider mas estable hoy fue {strongest_signals[0].signal_label} con Top 3 de {round(strongest_signals[0].hit_top_3_rate * 100, 1)}%."
            )
        if weakest_signals:
            notes.append(
                f"La senal lider mas floja hoy fue {weakest_signals[0].signal_label} con Top 3 de {round(weakest_signals[0].hit_top_3_rate * 100, 1)}%."
            )
        db_service.save_prediction_window_reviews(persisted_reviews)

        return PredictionReviewSummary(
            generated_at=utc_now(),
            draw_date=draw_date,
            methodology_version=self.METHODOLOGY_VERSION,
            evaluated_draws=totals["evaluated"],
            hit_top_1=totals["top1"],
            hit_top_3=totals["top3"],
            hit_top_5=totals["top5"],
            hit_top_1_rate=round(totals["top1"] / totals["evaluated"], 4) if totals["evaluated"] else 0,
            hit_top_3_rate=round(totals["top3"] / totals["evaluated"], 4) if totals["evaluated"] else 0,
            hit_top_5_rate=round(totals["top5"] / totals["evaluated"], 4) if totals["evaluated"] else 0,
            by_lottery=lottery_rows,
            by_hour=hour_rows,
            by_signal=signal_rows,
            strongest_hours=strongest_hours,
            weakest_hours=weakest_hours,
            strongest_signals=strongest_signals,
            weakest_signals=weakest_signals,
            windows=sorted(windows, key=lambda item: (item.draw_date, item.draw_time_local, item.canonical_lottery_name)),
            notes=notes,
        )

    def _build_external_strategy_context(self, reference_local: datetime) -> dict[str, Any]:
        target_date = reference_local.date()
        self.ensure_daily_external_snapshots(target_date=target_date, force_refresh=False)
        strategy_sources = self._load_strategy_sources(force_refresh=False, target_date=target_date, frozen=True)
        enjaulados = self._load_enjaulados_data(force_refresh=False, target_date=target_date, frozen=True)
        today_key = reference_local.date().isoformat()
        today_results = [
            item
            for item in db_service.get_results(start_date=today_key, end_date=today_key, limit=None)
            if self._coerce_datetime(item["draw_datetime_utc"]) <= reference_local.astimezone(timezone.utc)
        ]

        adaptive_weights = {}
        consensus_counts = Counter()
        adaptive_scores = Counter()
        for source in strategy_sources:
            animals = source.get("animals", [])
            numbers = [int(item.get("animal_number")) for item in animals]
            if today_results:
                hit_count = sum(1 for result in today_results if int(result["animal_number"]) in numbers)
                hit_rate = hit_count / len(today_results)
            else:
                hit_count = 0
                hit_rate = 0
            source_weight = 0.0 if hit_rate < 0.08 else min(0.5 + hit_rate, 1.5)
            adaptive_weights[source.get("key")] = source_weight
            for animal in animals:
                key = (int(animal.get("animal_number")), animal.get("animal_name") or get_animal_name(int(animal.get("animal_number"))))
                consensus_counts[key] += 1
                adaptive_scores[key] += source_weight

        enjaulados_by_lottery = {}
        for lottery in enjaulados.lotteries:
            enjaulados_by_lottery[lottery.canonical_lottery_name] = {
                (item.animal_number, item.animal_name): item.days_without_hit for item in lottery.items
            }

        return {
            "consensus_counts": consensus_counts,
            "adaptive_scores": adaptive_scores,
            "enjaulados_by_lottery": enjaulados_by_lottery,
            "source_count": max(len(strategy_sources), 1),
            "adaptive_max": max(adaptive_scores.values(), default=1),
            "enjaulado_max": max(
                (days for lottery_map in enjaulados_by_lottery.values() for days in lottery_map.values()),
                default=1,
            ),
        }

    def build_strategies_summary(self, force_refresh: bool = False) -> StrategiesResponse:
        today = local_now().date()
        self.ensure_daily_external_snapshots(target_date=today, force_refresh=force_refresh)
        strategies = self._load_strategy_sources(
            force_refresh=False,
            target_date=today,
            frozen=not force_refresh,
        )
        today_results = [
            item
            for item in db_service.get_results(start_date=today.isoformat(), end_date=today.isoformat(), limit=None)
            if item.get("canonical_lottery_name") in PRIMARY_LOTTERIES
        ]
        latest_prediction = db_service.get_latest_prediction_run() or {}
        latest_summary = latest_prediction.get("summary") or {}
        if not latest_summary:
            latest_summary = self.build_possible_results_summary().model_dump()

        system_top5_by_lottery = {}
        for lottery in latest_summary.get("lotteries", []):
            draw_predictions = lottery.get("draw_predictions") or []
            if draw_predictions:
                first_window = draw_predictions[0]
                system_top5_by_lottery[lottery.get("canonical_lottery_name")] = [
                    int(candidate.get("animal_number"))
                    for candidate in first_window.get("candidates", [])[:5]
                ]
            else:
                system_top5_by_lottery[lottery.get("canonical_lottery_name")] = [
                    int(candidate.get("animal_number"))
                    for candidate in lottery.get("top_5", [])[:5]
                ]

        performance_rows = []
        consensus_counter = defaultdict(set)
        hits_counter = Counter()
        actual_numbers_today = [int(item["animal_number"]) for item in today_results]

        for source in strategies:
            source_numbers = [int(item.get("animal_number")) for item in source.get("animals", [])]
            for animal_number in source_numbers:
                consensus_counter[animal_number].add(source.get("title"))
                hits_counter[animal_number] += actual_numbers_today.count(animal_number)

            matching_animals = []
            for animal_number in source_numbers:
                if animal_number in actual_numbers_today:
                    matching_animals.append(
                        {
                            "animal_number": animal_number,
                            "animal_name": get_animal_name(animal_number),
                        }
                    )

            overlap_labels = []
            for lottery_name, system_numbers in system_top5_by_lottery.items():
                overlaps = [number for number in source_numbers if number in system_numbers]
                if overlaps:
                    overlap_labels.append(
                        f"{lottery_name}: {', '.join(f'{number:02d}' for number in overlaps)}"
                    )

            performance_rows.append(
                StrategyPerformance(
                    key=source.get("key"),
                    title=source.get("title"),
                    hit_count_today=sum(actual_numbers_today.count(number) for number in source_numbers),
                    evaluated_results_today=len(today_results),
                    hit_rate_today=round(
                        (
                            sum(actual_numbers_today.count(number) for number in source_numbers)
                            / len(today_results)
                        ),
                        4,
                    )
                    if today_results
                    else 0,
                    matching_animals_today=matching_animals,
                    overlap_with_system_top5=overlap_labels,
                )
            )

        consensus_rows = []
        for animal_number, source_titles in sorted(
            consensus_counter.items(),
            key=lambda item: (len(item[1]), hits_counter[item[0]], -item[0]),
            reverse=True,
        ):
            overlap_labels = [
                lottery_name
                for lottery_name, system_numbers in system_top5_by_lottery.items()
                if animal_number in system_numbers
            ]
            consensus_rows.append(
                StrategyConsensusAnimal(
                    animal_number=animal_number,
                    animal_name=get_animal_name(animal_number),
                    mention_count=len(source_titles),
                    sources=sorted(source_titles),
                    overlap_with_system_top5=overlap_labels,
                    hits_today=hits_counter.get(animal_number, 0),
                )
            )

        notes = [
            "Las estrategias externas ya alimentan una capa de consenso y ajuste adaptativo dentro del ranking intradia.",
            "El consenso destaca animalitos repetidos entre varias fuentes y su cruce con el top 5 actual del sistema.",
        ]
        if today_results:
            notes.append(f"Hoy ya se evaluaron {len(today_results)} resultados confirmados contra estas fuentes externas.")

        return StrategiesResponse(
            generated_at=utc_now(),
            draw_date=today,
            methodology_version=self.METHODOLOGY_VERSION,
            sources=strategies,
            performance=sorted(performance_rows, key=lambda item: (item.hit_count_today, item.hit_rate_today), reverse=True),
            consensus=consensus_rows[:12],
            notes=notes,
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
