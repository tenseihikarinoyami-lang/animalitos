from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.core.config import settings


metadata = MetaData()

results_table = Table(
    "results",
    metadata,
    Column("dedupe_key", String(255), primary_key=True),
    Column("canonical_lottery_name", String(120), nullable=False, index=True),
    Column("source_lottery_name", String(120), nullable=False),
    Column("draw_date", Date, nullable=False, index=True),
    Column("draw_time_local", String(10), nullable=False),
    Column("draw_datetime_utc", DateTime(timezone=True), nullable=False, index=True),
    Column("animal_number", Integer, nullable=False),
    Column("animal_name", String(120), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("source_page", String(80), nullable=True),
)

draw_schedules_table = Table(
    "draw_schedules",
    metadata,
    Column("canonical_lottery_name", String(120), primary_key=True),
    Column("display_name", String(120), nullable=False),
    Column("times", JSONB, nullable=False),
    Column("source_pages", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
)

users_table = Table(
    "users",
    metadata,
    Column("username", String(120), primary_key=True),
    Column("email", String(255), nullable=True),
    Column("full_name", String(255), nullable=True),
    Column("password", Text, nullable=False),
    Column("role", String(32), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("must_change_password", Boolean, nullable=False, default=False),
    Column("password_changed_at", DateTime(timezone=True), nullable=True),
)

ingestion_runs_table = Table(
    "ingestion_runs",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("trigger", String(120), nullable=False),
    Column("status", String(32), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("duration_seconds", Float, nullable=False),
    Column("results_found", Integer, nullable=False),
    Column("new_results", Integer, nullable=False),
    Column("duplicates", Integer, nullable=False),
    Column("errors", JSONB, nullable=False),
    Column("source_urls", JSONB, nullable=False),
    Column("lotteries_seen", JSONB, nullable=False),
    Column("coverage_start", Date, nullable=True),
    Column("coverage_end", Date, nullable=True),
    Column("parser_version", String(80), nullable=True),
    Column("missing_slots", JSONB, nullable=False),
    Column("source_status", JSONB, nullable=False),
    Column("source_reports", JSONB, nullable=False),
)

analytics_snapshots_table = Table(
    "analytics_snapshots",
    metadata,
    Column("snapshot_key", String(160), primary_key=True),
    Column("generated_at", DateTime(timezone=True), nullable=True),
    Column("payload", JSONB, nullable=False),
)

prediction_runs_table = Table(
    "prediction_runs",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("delivery_status", String(32), nullable=False),
    Column("preview_only", Boolean, nullable=False, default=False),
    Column("target_lotteries", JSONB, nullable=False),
    Column("top_n", Integer, nullable=False),
    Column("summary", JSONB, nullable=False),
    Column("telegram_sent", Boolean, nullable=False, default=False),
)

model_training_examples_table = Table(
    "model_training_examples",
    metadata,
    Column("example_key", String(255), primary_key=True),
    Column("segment_key", String(120), nullable=False, index=True),
    Column("canonical_lottery_name", String(120), nullable=False, index=True),
    Column("draw_date", Date, nullable=False, index=True),
    Column("draw_time_local", String(10), nullable=False),
    Column("animal_number", Integer, nullable=False),
    Column("label_hit", Boolean, nullable=False),
    Column("methodology_version", String(80), nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("features", JSONB, nullable=False),
    Column("metadata", JSONB, nullable=False),
)

model_versions_table = Table(
    "model_versions",
    metadata,
    Column("model_key", String(160), primary_key=True),
    Column("segment_key", String(120), nullable=False, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column("trained_at", DateTime(timezone=True), nullable=False),
    Column("training_start_date", Date, nullable=True),
    Column("training_end_date", Date, nullable=True),
    Column("ensemble_weights", JSONB, nullable=False),
    Column("validation_metrics", JSONB, nullable=False),
    Column("calibration_method", String(32), nullable=True),
    Column("artifact", JSONB, nullable=False),
    Column("notes", JSONB, nullable=False),
)

prediction_window_reviews_table = Table(
    "prediction_window_reviews",
    metadata,
    Column("review_key", String(255), primary_key=True),
    Column("segment_key", String(120), nullable=False, index=True),
    Column("canonical_lottery_name", String(120), nullable=False, index=True),
    Column("draw_date", Date, nullable=False, index=True),
    Column("draw_time_local", String(10), nullable=False),
    Column("actual_animal_number", Integer, nullable=False),
    Column("actual_animal_name", String(120), nullable=False),
    Column("predicted_at", DateTime(timezone=True), nullable=True),
    Column("model_key", String(160), nullable=True),
    Column("ensemble_version", String(80), nullable=True),
    Column("lead_signal_key", String(80), nullable=True),
    Column("confidence_band", String(32), nullable=True),
    Column("stability_score", Float, nullable=True),
    Column("hit_top_1", Boolean, nullable=False, default=False),
    Column("hit_top_3", Boolean, nullable=False, default=False),
    Column("hit_top_5", Boolean, nullable=False, default=False),
    Column("payload", JSONB, nullable=False),
)

admin_audit_logs_table = Table(
    "admin_audit_logs",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("action", String(120), nullable=False),
    Column("actor_username", String(120), nullable=False),
    Column("actor_role", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("source_ip", String(120), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("details", JSONB, nullable=False),
)

_engine: Engine | None = None


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine() -> Engine | None:
    global _engine
    if not settings.use_postgres or not settings.database_url:
        return None
    if _engine is None:
        _engine = create_engine(
            _normalize_database_url(settings.database_url),
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def initialize_postgres() -> bool:
    engine = get_engine()
    if engine is None:
        return False

    try:
        metadata.create_all(engine)
        return True
    except Exception as exc:
        print(f"Postgres initialization error: {exc}")
        return False


postgres_initialized = initialize_postgres()
