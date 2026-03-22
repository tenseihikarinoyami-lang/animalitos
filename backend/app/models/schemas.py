from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    username: str
    email: EmailStr | None = None
    full_name: str | None = None
    role: str = "user"


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase):
    id: str
    is_active: bool = True
    created_at: datetime | None = None
    must_change_password: bool = False
    password_changed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class ResultRecord(BaseModel):
    canonical_lottery_name: str
    source_lottery_name: str
    draw_date: date
    draw_time_local: str
    draw_datetime_utc: datetime
    animal_number: int
    animal_name: str
    source_url: str
    status: str = "confirmed"
    dedupe_key: str
    ingested_at: datetime
    source_page: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ResultQueryResponse(BaseModel):
    items: list[ResultRecord]
    total: int
    filters: dict[str, Any]


class ScheduleEntry(BaseModel):
    canonical_lottery_name: str
    display_name: str
    times: list[str]
    source_pages: list[str]
    status: str = "active"


class IngestionRun(BaseModel):
    id: str | None = None
    trigger: str
    status: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    results_found: int
    new_results: int
    duplicates: int
    errors: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    lotteries_seen: list[str] = Field(default_factory=list)
    coverage_start: date | None = None
    coverage_end: date | None = None
    parser_version: str | None = None
    missing_slots: dict[str, list[str]] = Field(default_factory=dict)
    source_status: dict[str, str] = Field(default_factory=dict)


class LotteryOverviewCard(BaseModel):
    canonical_lottery_name: str
    total_results_today: int
    expected_results_today: int
    expected_by_now: int
    missing_draws_today: int
    completion_ratio: float
    last_result: ResultRecord | None = None
    next_draw_time_local: str | None = None
    next_draw: dict[str, Any] | None = None


class DashboardOverview(BaseModel):
    generated_at: datetime
    total_results_today: int
    missing_draws_today: int
    next_draw: dict[str, Any] | None = None
    latest_results: list[ResultRecord]
    primary_lotteries: list[LotteryOverviewCard]
    latest_ingestion_run: IngestionRun | None = None


class TrendBucket(BaseModel):
    label: str
    value: int
    lottery_name: str | None = None
    animal_number: int | None = None
    animal_name: str | None = None


class ScoreComponent(BaseModel):
    key: str
    label: str
    weight: float


class CandidateSignal(BaseModel):
    key: str
    label: str
    contribution: float
    weight: float
    raw_value: float | None = None
    intensity: str | None = None


class AnalyticsTrends(BaseModel):
    generated_at: datetime
    days: int
    lottery_name: str | None = None
    frequency: list[TrendBucket]
    hourly_distribution: list[TrendBucket]
    daily_volume: list[TrendBucket]
    streaks: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]


class PossibleResultCandidate(BaseModel):
    animal_number: int
    animal_name: str
    score: float
    overall_hits: int
    recent_hits: int
    remaining_time_hits: int
    last4_slot_hits: int = 0
    draws_since_last_seen: int
    seen_today: bool = False
    weekday_slot_hits: int = 0
    daypart_hits: int = 0
    pair_context_hits: int = 0
    trio_context_hits: int = 0
    exact_context_hits: int = 0
    same_day_repeat_hits: int = 0
    cross_lottery_hits: int = 0
    cross_lottery_exact_hits: int = 0
    strategy_hits: int = 0
    strategy_weighted_hits: float = 0
    enjaulado_days_without_hit: int = 0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    strongest_signals: list[CandidateSignal] = Field(default_factory=list)
    rank_delta: int | None = None
    previous_rank: int | None = None
    score_delta: float | None = None
    movement_summary: str | None = None


class DrawPredictionCandidate(BaseModel):
    animal_number: int
    animal_name: str
    score: float
    slot_hits: int
    recent_slot_hits: int
    last4_slot_hits: int = 0
    transition_hits: int
    coincidence_hits: int
    overall_hits: int
    recent_hits: int
    draws_since_last_seen: int
    weekday_slot_hits: int = 0
    daypart_hits: int = 0
    pair_context_hits: int = 0
    trio_context_hits: int = 0
    exact_context_hits: int = 0
    same_day_repeat_hits: int = 0
    cross_lottery_hits: int = 0
    cross_lottery_exact_hits: int = 0
    strategy_hits: int = 0
    strategy_weighted_hits: float = 0
    enjaulado_days_without_hit: int = 0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    strongest_signals: list[CandidateSignal] = Field(default_factory=list)
    rank_delta: int | None = None
    previous_rank: int | None = None
    score_delta: float | None = None
    movement_summary: str | None = None


class DrawPredictionWindow(BaseModel):
    draw_time_local: str
    observed_prefix: list[int] = Field(default_factory=list)
    minutes_until: int | None = None
    daypart: str | None = None
    top_candidate_changed: bool = False
    change_summary: str | None = None
    candidates: list[DrawPredictionCandidate]


class LotteryPossibleResults(BaseModel):
    canonical_lottery_name: str
    history_results_considered: int
    history_days_covered: int
    today_results_count: int
    remaining_draws_today: int
    next_draw_time_local: str | None = None
    target_draw_times: list[str] = Field(default_factory=list)
    candidates: list[PossibleResultCandidate]
    top_3: list[PossibleResultCandidate] = Field(default_factory=list)
    top_5: list[PossibleResultCandidate] = Field(default_factory=list)
    top_10: list[PossibleResultCandidate] = Field(default_factory=list)
    draw_predictions: list[DrawPredictionWindow] = Field(default_factory=list)


class PossibleResultsSummary(BaseModel):
    generated_at: datetime
    reference_date: date | None = None
    reference_time_local: str | None = None
    methodology_version: str
    methodology: str
    disclaimer: str
    baseline_methodology_version: str | None = None
    history_days_covered: int
    history_results_considered: int
    score_components: list[ScoreComponent]
    last_backfill_at: datetime | None = None
    change_alerts: list[str] = Field(default_factory=list)
    lotteries: list[LotteryPossibleResults]


class RefreshResponse(BaseModel):
    ingestion_run: IngestionRun
    overview: DashboardOverview


class BackfillRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    days: int | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class AdminUserCreateRequest(BaseModel):
    username: str
    temporary_password: str = Field(min_length=8)
    role: str = "user"
    full_name: str | None = None
    email: EmailStr | None = None


class AdminResetPasswordRequest(BaseModel):
    temporary_password: str = Field(min_length=8)


class PredictionRunRequest(BaseModel):
    top_n: int = Field(default=5, ge=1, le=10)
    lotteries: list[str] = Field(default_factory=list)
    preview_only: bool = False


class PredictionRunRecord(BaseModel):
    id: str | None = None
    generated_at: datetime
    delivery_status: str
    preview_only: bool = False
    target_lotteries: list[str] = Field(default_factory=list)
    top_n: int
    summary: PossibleResultsSummary
    telegram_sent: bool = False


class BacktestingHourMetric(BaseModel):
    lottery_name: str
    draw_time_local: str
    total_draws: int
    top_1_hits: int
    top_3_hits: int
    top_5_hits: int
    top_1_rate: float = 0
    top_3_rate: float = 0
    top_5_rate: float = 0
    baseline_top_1_hits: int = 0
    baseline_top_3_hits: int = 0
    baseline_top_5_hits: int = 0
    baseline_top_1_rate: float = 0
    baseline_top_3_rate: float = 0
    baseline_top_5_rate: float = 0
    beats_baseline: bool = False


class BacktestingLotteryMetric(BaseModel):
    lottery_name: str
    total_draws: int
    top_1_hits: int
    top_3_hits: int
    top_5_hits: int
    top_1_rate: float
    top_3_rate: float
    top_5_rate: float
    baseline_top_1_hits: int = 0
    baseline_top_3_hits: int = 0
    baseline_top_5_hits: int = 0
    baseline_top_1_rate: float = 0
    baseline_top_3_rate: float = 0
    baseline_top_5_rate: float = 0
    lift_top_3: float = 0
    beats_baseline: bool = False


class CalibrationAdjustment(BaseModel):
    key: str
    label: str
    previous_weight: float
    current_weight: float
    delta: float
    rationale: str


class BacktestingSummary(BaseModel):
    generated_at: datetime
    days: int
    methodology_version: str
    baseline_methodology_version: str | None = None
    overall_total_draws: int
    overall_top_1_rate: float
    overall_top_3_rate: float
    overall_top_5_rate: float
    baseline_overall_top_1_rate: float = 0
    baseline_overall_top_3_rate: float = 0
    baseline_overall_top_5_rate: float = 0
    beats_baseline: bool = False
    by_lottery: list[BacktestingLotteryMetric]
    by_hour: list[BacktestingHourMetric]
    calibration_summary: str | None = None
    calibration_notes: list[str] = Field(default_factory=list)
    weight_adjustments: list[CalibrationAdjustment] = Field(default_factory=list)
    strongest_lotteries: list[BacktestingLotteryMetric] = Field(default_factory=list)
    weakest_lotteries: list[BacktestingLotteryMetric] = Field(default_factory=list)
    strongest_hours: list[BacktestingHourMetric] = Field(default_factory=list)
    weakest_hours: list[BacktestingHourMetric] = Field(default_factory=list)


class PredictionReviewWindow(BaseModel):
    canonical_lottery_name: str
    draw_date: date
    draw_time_local: str
    actual_animal_number: int
    actual_animal_name: str
    predicted_at: datetime | None = None
    prediction_delivery_status: str | None = None
    predicted_top_1_number: int | None = None
    predicted_top_1_name: str | None = None
    lead_signal_key: str | None = None
    lead_signal_label: str | None = None
    top_1: list[int] = Field(default_factory=list)
    top_3: list[int] = Field(default_factory=list)
    top_5: list[int] = Field(default_factory=list)
    hit_top_1: bool = False
    hit_top_3: bool = False
    hit_top_5: bool = False
    actual_rank: int | None = None
    prediction_available: bool = False


class PredictionReviewLotteryMetric(BaseModel):
    canonical_lottery_name: str
    evaluated_draws: int
    hit_top_1: int
    hit_top_3: int
    hit_top_5: int
    hit_top_1_rate: float
    hit_top_3_rate: float
    hit_top_5_rate: float


class PredictionReviewHourMetric(BaseModel):
    canonical_lottery_name: str
    draw_time_local: str
    evaluated_draws: int
    hit_top_1: int
    hit_top_3: int
    hit_top_5: int
    hit_top_1_rate: float
    hit_top_3_rate: float
    hit_top_5_rate: float


class PredictionReviewSignalMetric(BaseModel):
    signal_key: str
    signal_label: str
    evaluated_draws: int
    hit_top_1: int
    hit_top_3: int
    hit_top_5: int
    hit_top_1_rate: float
    hit_top_3_rate: float
    hit_top_5_rate: float


class PredictionReviewSummary(BaseModel):
    generated_at: datetime
    draw_date: date
    methodology_version: str
    evaluated_draws: int
    hit_top_1: int
    hit_top_3: int
    hit_top_5: int
    hit_top_1_rate: float
    hit_top_3_rate: float
    hit_top_5_rate: float
    by_lottery: list[PredictionReviewLotteryMetric] = Field(default_factory=list)
    by_hour: list[PredictionReviewHourMetric] = Field(default_factory=list)
    by_signal: list[PredictionReviewSignalMetric] = Field(default_factory=list)
    strongest_hours: list[PredictionReviewHourMetric] = Field(default_factory=list)
    weakest_hours: list[PredictionReviewHourMetric] = Field(default_factory=list)
    strongest_signals: list[PredictionReviewSignalMetric] = Field(default_factory=list)
    weakest_signals: list[PredictionReviewSignalMetric] = Field(default_factory=list)
    windows: list[PredictionReviewWindow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EnjauladoAnimal(BaseModel):
    animal_number: int
    animal_name: str
    last_seen_date: date | None = None
    days_without_hit: int


class EnjauladosLotterySummary(BaseModel):
    canonical_lottery_name: str
    source_url: str
    generated_at: datetime
    items: list[EnjauladoAnimal] = Field(default_factory=list)


class EnjauladosResponse(BaseModel):
    generated_at: datetime
    lotteries: list[EnjauladosLotterySummary] = Field(default_factory=list)


class StrategyAnimal(BaseModel):
    animal_number: int
    animal_name: str


class StrategySource(BaseModel):
    key: str
    title: str
    source_url: str
    generated_at: datetime
    animals: list[StrategyAnimal] = Field(default_factory=list)


class StrategyPerformance(BaseModel):
    key: str
    title: str
    hit_count_today: int
    evaluated_results_today: int
    hit_rate_today: float
    matching_animals_today: list[StrategyAnimal] = Field(default_factory=list)
    overlap_with_system_top5: list[str] = Field(default_factory=list)


class StrategyConsensusAnimal(BaseModel):
    animal_number: int
    animal_name: str
    mention_count: int
    sources: list[str] = Field(default_factory=list)
    overlap_with_system_top5: list[str] = Field(default_factory=list)
    hits_today: int = 0


class StrategiesResponse(BaseModel):
    generated_at: datetime
    draw_date: date
    methodology_version: str
    sources: list[StrategySource] = Field(default_factory=list)
    performance: list[StrategyPerformance] = Field(default_factory=list)
    consensus: list[StrategyConsensusAnimal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QualityLotteryRecord(BaseModel):
    draw_date: date
    canonical_lottery_name: str
    expected_slots: int
    found_slots: int
    missing_slots: list[str] = Field(default_factory=list)
    status: str
    source_status: str | None = None
    coverage_ratio: float


class QualityReportResponse(BaseModel):
    generated_at: datetime
    days: int
    items: list[QualityLotteryRecord]


class AuditLogEntry(BaseModel):
    id: str | None = None
    action: str
    actor_username: str
    actor_role: str
    status: str
    source_ip: str | None = None
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class BackfillJobStatus(BaseModel):
    job_id: str
    status: str
    trigger: str | None = None
    message: str | None = None
    start_date: date
    end_date: date
    total_days: int
    completed_days: int = 0
    current_date: date | None = None
    results_found: int = 0
    new_results: int = 0
    duplicates: int = 0
    empty_days: list[str] = Field(default_factory=list)
    errors_count: int = 0
    last_error: str | None = None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    ingestion_run_id: str | None = None


class SystemStatusResponse(BaseModel):
    generated_at: datetime
    firebase_connected: bool
    database_provider: str
    telegram_configured: bool
    scheduler_running: bool
    scheduler_mode: str = "internal"
    scheduler_last_received_at: datetime | None = None
    scheduler_last_completed_at: datetime | None = None
    scheduler_last_status: str | None = None
    scheduler_last_kind: str | None = None
    scheduler_message: str | None = None
    scheduler_stale: bool = False
    latest_successful_run: IngestionRun | None = None
    latest_failed_run: IngestionRun | None = None
    latest_backfill_run: IngestionRun | None = None
    latest_prediction_run: PredictionRunRecord | None = None
    active_backfill: BackfillJobStatus | None = None
    total_results: int
    warnings: list[str] = Field(default_factory=list)


class AdminActionResponse(BaseModel):
    message: str
    details: dict[str, Any]


ANIMALITOS_MAP = {
    0: "Delfin",
    1: "Carnero",
    2: "Toro",
    3: "Ciempies",
    4: "Alacran",
    5: "Leon",
    6: "Rana",
    7: "Perico",
    8: "Raton",
    9: "Aguila",
    10: "Tigre",
    11: "Gato",
    12: "Caballo",
    13: "Mono",
    14: "Paloma",
    15: "Zorro",
    16: "Oso",
    17: "Pavo",
    18: "Burro",
    19: "Chivo",
    20: "Cochino",
    21: "Gallo",
    22: "Camello",
    23: "Cebra",
    24: "Iguana",
    25: "Gallina",
    26: "Vaca",
    27: "Perro",
    28: "Zamuro",
    29: "Elefante",
    30: "Caiman",
    31: "Lapa",
    32: "Ardilla",
    33: "Pescado",
    34: "Venado",
    35: "Jirafa",
    36: "Culebra",
    37: "Tiburon",
    38: "Cangrejo",
    39: "Pavo Real",
    40: "Avispa",
    41: "Canguro",
    42: "Tucan",
    43: "Mariposa",
    44: "Chiguire",
    45: "Garza",
    46: "Puma",
    47: "Pavo Real",
    48: "Avestruz",
    49: "Cebra Real",
    50: "Canario",
    51: "Flamenco",
    52: "Pulpo",
    53: "Cachalote",
    54: "Grillo",
    55: "Oso Hormiguero",
    56: "Mula",
    57: "Pavito",
    58: "Hormiga",
    59: "Hormiga Reina",
    60: "Escorpion",
    61: "Panda",
    62: "Cachicamo",
    63: "Cangrejo",
    64: "Gavilan",
    65: "Arana",
    66: "Lobo",
    67: "Avestruz",
    68: "Jaguar",
    69: "Conejo",
    70: "Bisonte",
    71: "Guacamaya",
    72: "Gorila",
    73: "Hipopotamo",
    74: "Bufalo",
    75: "Patronus",
    76: "Reno",
    77: "Pina",
    78: "Mango",
    79: "Gusano",
    80: "Coco",
    81: "Cereza",
    82: "Manzana",
    83: "Pera",
    84: "Melon",
    85: "Uva",
    86: "Naranja",
    87: "Limon",
    88: "Erizo de Mar",
    89: "Guayaba",
    90: "Huron",
    91: "Agua",
    92: "Fuego",
    93: "Aire",
    94: "Paujil",
    95: "Viejo",
    96: "Nina",
    97: "Espada",
    98: "Anillo",
    99: "Beso",
    100: "Ballena",
}


def get_animal_name(number: int) -> str:
    return ANIMALITOS_MAP.get(number, "Desconocido")
