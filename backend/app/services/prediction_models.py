import base64
import pickle
from collections import defaultdict
from datetime import date

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss


INTERNAL_COMPONENT_KEYS = [
    "slot_recent_14d",
    "slot_historical_90d",
    "slot_last4_occurrences",
    "weekday_slot_frequency",
    "daypart_frequency",
    "recent_frequency_7d",
    "recent_frequency_30d",
    "historical_frequency_90d",
    "last_transition",
    "pair_context",
    "trio_context",
    "prefix_overlap",
    "exact_prefix_match",
    "cross_lottery_overlap",
    "cross_lottery_exact",
    "overdue_gap",
    "same_day_repeat_pattern",
]

EXTERNAL_COMPONENT_KEYS = [
    "strategy_consensus",
    "strategy_adaptive",
    "enjaulado_pressure",
]

FEATURE_NAMES = [
    "rule_score",
    "external_prior",
    "slot_hits",
    "recent_slot_hits",
    "last4_slot_hits",
    "transition_hits",
    "coincidence_hits",
    "overall_hits",
    "recent_hits",
    "draws_since_last_seen",
    "weekday_slot_hits",
    "daypart_hits",
    "pair_context_hits",
    "trio_context_hits",
    "exact_context_hits",
    "same_day_repeat_hits",
    "cross_lottery_hits",
    "cross_lottery_exact_hits",
    "strategy_hits",
    "strategy_weighted_hits",
    "enjaulado_days_without_hit",
    "minute_bucket",
    "daypart_bucket",
    "weekday_bucket",
    "is_halfhour",
]


def build_segment_key(lottery_name: str, draw_time_local: str) -> str:
    minute_bucket = draw_time_local.split(":")[1] if ":" in draw_time_local else "00"
    if lottery_name == "Lotto Activo":
        return "lotto-activo-hourly"
    if lottery_name == "La Granjita":
        return "la-granjita-hourly"
    if lottery_name == "Lotto Activo Internacional":
        return "internacional-halfhour" if minute_bucket == "30" else "internacional-hourly"
    return "unknown"


def serialize_artifact(value) -> str:
    return base64.b64encode(pickle.dumps(value)).decode("ascii")


def deserialize_artifact(value: str):
    return pickle.loads(base64.b64decode(value.encode("ascii")))


def normalize_window_values(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [1.0 if maximum > 0 else 0.0 for _ in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def build_rule_score(score_breakdown: dict[str, float]) -> float:
    return round(sum(float(score_breakdown.get(key, 0.0)) for key in INTERNAL_COMPONENT_KEYS), 4)


def build_external_raw_prior(score_breakdown: dict[str, float]) -> float:
    return round(sum(float(score_breakdown.get(key, 0.0)) for key in EXTERNAL_COMPONENT_KEYS), 4)


def normalize_external_priors(values: list[float], cap: float = 1.0) -> list[float]:
    normalized = normalize_window_values(values)
    return [min(max(value, 0.0), cap) for value in normalized]


def build_ensemble_score(model_probability: float, normalized_rule_score: float, external_prior: float) -> float:
    return round(
        (0.60 * float(model_probability))
        + (0.30 * float(normalized_rule_score))
        + (0.10 * float(external_prior)),
        6,
    )


def compute_window_stability(
    current_top_numbers: list[int],
    previous_top_numbers: list[int] | None,
    ensemble_gap: float,
    weak_sample: bool,
) -> float:
    overlap_score = 0.5
    if previous_top_numbers:
        overlap = len(set(current_top_numbers[:3]).intersection(previous_top_numbers[:3]))
        overlap_score = overlap / 3

    gap_score = min(max(float(ensemble_gap) / 0.18, 0.0), 1.0)
    stability = (gap_score * 0.6) + (overlap_score * 0.4)
    if weak_sample:
        stability -= 0.15
    return round(min(max(stability, 0.0), 1.0), 4)


def stable_probability_band(probability: float, stability_score: float, weak_sample: bool) -> str:
    adjusted = (probability * 0.75) + (stability_score * 0.25)
    if weak_sample:
        adjusted -= 0.12
    if adjusted >= 0.66:
        return "alta"
    if adjusted >= 0.42:
        return "media"
    return "baja"


def compute_window_topk_metrics(predictions: list[dict]) -> dict:
    by_window = defaultdict(list)
    for row in predictions:
        by_window[row["window_key"]].append(row)

    totals = {"windows": 0, "top1": 0, "top3": 0, "top5": 0, "baseline_top3": 0, "baseline_top5": 0}
    for window_rows in by_window.values():
        totals["windows"] += 1
        ranked = sorted(window_rows, key=lambda item: (item["probability"], item["rule_score"]), reverse=True)
        baseline = sorted(window_rows, key=lambda item: item["rule_score"], reverse=True)
        hits = [item for item in ranked if item["label_hit"]]
        baseline_hits = [item for item in baseline if item["label_hit"]]
        actual_number = hits[0]["animal_number"] if hits else None
        baseline_actual = baseline_hits[0]["animal_number"] if baseline_hits else None
        ranked_numbers = [item["animal_number"] for item in ranked]
        baseline_numbers = [item["animal_number"] for item in baseline]
        if actual_number in ranked_numbers[:1]:
            totals["top1"] += 1
        if actual_number in ranked_numbers[:3]:
            totals["top3"] += 1
        if actual_number in ranked_numbers[:5]:
            totals["top5"] += 1
        if baseline_actual in baseline_numbers[:3]:
            totals["baseline_top3"] += 1
        if baseline_actual in baseline_numbers[:5]:
            totals["baseline_top5"] += 1
    return totals


def _bucket_daypart(value: str | None) -> int:
    mapping = {"manana": 0, "tarde": 1, "noche": 2}
    return mapping.get((value or "").lower(), 0)


def _prepare_matrix(examples: list[dict]) -> list[list[float]]:
    matrix = []
    for example in examples:
        features = example.get("features", {})
        matrix.append([float(features.get(name, 0.0)) for name in FEATURE_NAMES])
    return matrix


def _prepare_labels(examples: list[dict]) -> list[int]:
    return [1 if example.get("label_hit") else 0 for example in examples]


def _split_dates(unique_dates: list[date]) -> tuple[set[date], set[date], set[date]] | None:
    if len(unique_dates) < 6:
        return None
    total = len(unique_dates)
    train_cut = max(int(total * 0.6), 3)
    calib_cut = max(int(total * 0.8), train_cut + 1)
    if calib_cut >= total:
        calib_cut = total - 1
    train_dates = set(unique_dates[:train_cut])
    calib_dates = set(unique_dates[train_cut:calib_cut])
    validation_dates = set(unique_dates[calib_cut:])
    if not train_dates or not calib_dates or not validation_dates:
        return None
    return train_dates, calib_dates, validation_dates


def _fit_calibrator(method: str, scores: list[float], labels: list[int]):
    if method == "isotonic":
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(scores, labels)
        return calibrator
    calibrator = LogisticRegression(solver="lbfgs")
    calibrator.fit([[score] for score in scores], labels)
    return calibrator


def _apply_calibrator(calibrator, method: str, scores: list[float]) -> list[float]:
    if method == "isotonic":
        return [float(value) for value in calibrator.predict(scores)]
    return [float(value) for value in calibrator.predict_proba([[score] for score in scores])[:, 1]]


def train_segment_model(segment_key: str, examples: list[dict]) -> dict | None:
    if len(examples) < 300:
        return None

    normalized_examples = []
    for example in examples:
        draw_date = example.get("draw_date")
        if isinstance(draw_date, str):
            draw_date = date.fromisoformat(draw_date)
        normalized = dict(example)
        normalized["draw_date"] = draw_date
        normalized_examples.append(normalized)

    unique_dates = sorted({item["draw_date"] for item in normalized_examples})
    split = _split_dates(unique_dates)
    if split is None:
        return None
    train_dates, calib_dates, validation_dates = split

    train_examples = [item for item in normalized_examples if item["draw_date"] in train_dates]
    calib_examples = [item for item in normalized_examples if item["draw_date"] in calib_dates]
    validation_examples = [item for item in normalized_examples if item["draw_date"] in validation_dates]
    if len(train_examples) < 150 or len(calib_examples) < 50 or len(validation_examples) < 50:
        return None

    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_depth=4,
        max_iter=140,
        min_samples_leaf=20,
        random_state=42,
    )
    model.fit(_prepare_matrix(train_examples), _prepare_labels(train_examples))

    calibration_scores = [float(value) for value in model.predict_proba(_prepare_matrix(calib_examples))[:, 1]]
    calibration_labels = _prepare_labels(calib_examples)
    validation_scores = [float(value) for value in model.predict_proba(_prepare_matrix(validation_examples))[:, 1]]
    validation_labels = _prepare_labels(validation_examples)

    best_method = None
    best_calibrator = None
    best_metric = None
    best_predictions = None
    for method in ("sigmoid", "isotonic"):
        calibrator = _fit_calibrator(method, calibration_scores, calibration_labels)
        calibrated_scores = _apply_calibrator(calibrator, method, validation_scores)
        metric = brier_score_loss(validation_labels, calibrated_scores)
        predictions = []
        for example, probability in zip(validation_examples, calibrated_scores):
            predictions.append(
                {
                    "window_key": example["metadata"]["window_key"],
                    "animal_number": example["animal_number"],
                    "probability": probability,
                    "rule_score": example["features"].get("rule_score", 0.0),
                    "label_hit": example["label_hit"],
                }
            )
        topk_metrics = compute_window_topk_metrics(predictions)
        ranking_score = (
            round((topk_metrics["top5"] / max(topk_metrics["windows"], 1)), 4),
            round((topk_metrics["top3"] / max(topk_metrics["windows"], 1)), 4),
            -round(metric, 6),
        )
        if best_metric is None or ranking_score > best_metric:
            best_metric = ranking_score
            best_method = method
            best_calibrator = calibrator
            best_predictions = predictions

    topk_metrics = compute_window_topk_metrics(best_predictions or [])
    validation_windows = max(topk_metrics["windows"], 1)
    return {
        "segment_key": segment_key,
        "trained_examples": len(normalized_examples),
        "training_start_date": min(unique_dates),
        "training_end_date": max(unique_dates),
        "calibration_method": best_method,
        "artifact": {
            "model": serialize_artifact(model),
            "calibrator": serialize_artifact(best_calibrator),
            "feature_names": FEATURE_NAMES,
        },
        "validation_metrics": {
            "validation_windows": topk_metrics["windows"],
            "validation_top_1_rate": round(topk_metrics["top1"] / validation_windows, 4),
            "validation_top_3_rate": round(topk_metrics["top3"] / validation_windows, 4),
            "validation_top_5_rate": round(topk_metrics["top5"] / validation_windows, 4),
            "baseline_top_3_rate": round(topk_metrics["baseline_top3"] / validation_windows, 4),
            "baseline_top_5_rate": round(topk_metrics["baseline_top5"] / validation_windows, 4),
            "brier_score": round(-best_metric[2], 6) if best_metric else None,
        },
    }


def predict_segment_probabilities(model_record: dict | None, feature_rows: list[dict]) -> list[float]:
    if not feature_rows:
        return []
    if not model_record:
        return [0.0 for _ in feature_rows]

    artifact = model_record.get("artifact") or {}
    if not artifact:
        return [0.0 for _ in feature_rows]

    model = deserialize_artifact(artifact["model"])
    calibrator = deserialize_artifact(artifact["calibrator"])
    feature_names = artifact.get("feature_names") or FEATURE_NAMES
    matrix = [[float(row.get(name, 0.0)) for name in feature_names] for row in feature_rows]
    base_scores = [float(value) for value in model.predict_proba(matrix)[:, 1]]
    method = model_record.get("calibration_method") or "sigmoid"
    return _apply_calibrator(calibrator, method, base_scores)


def make_feature_payload(candidate, *, rule_score: float, external_prior: float, draw_time_local: str, weekday: int, daypart: str) -> dict:
    minute_bucket = int(draw_time_local.split(":")[1]) if ":" in draw_time_local else 0
    return {
        "rule_score": round(rule_score, 6),
        "external_prior": round(external_prior, 6),
        "slot_hits": candidate.slot_hits,
        "recent_slot_hits": candidate.recent_slot_hits,
        "last4_slot_hits": candidate.last4_slot_hits,
        "transition_hits": candidate.transition_hits,
        "coincidence_hits": candidate.coincidence_hits,
        "overall_hits": candidate.overall_hits,
        "recent_hits": candidate.recent_hits,
        "draws_since_last_seen": candidate.draws_since_last_seen,
        "weekday_slot_hits": candidate.weekday_slot_hits,
        "daypart_hits": candidate.daypart_hits,
        "pair_context_hits": candidate.pair_context_hits,
        "trio_context_hits": candidate.trio_context_hits,
        "exact_context_hits": candidate.exact_context_hits,
        "same_day_repeat_hits": candidate.same_day_repeat_hits,
        "cross_lottery_hits": candidate.cross_lottery_hits,
        "cross_lottery_exact_hits": candidate.cross_lottery_exact_hits,
        "strategy_hits": candidate.strategy_hits,
        "strategy_weighted_hits": candidate.strategy_weighted_hits,
        "enjaulado_days_without_hit": candidate.enjaulado_days_without_hit,
        "minute_bucket": minute_bucket,
        "daypart_bucket": _bucket_daypart(daypart),
        "weekday_bucket": weekday,
        "is_halfhour": 1 if minute_bucket == 30 else 0,
    }
