from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.lottery_catalog import DEFAULT_DRAW_SCHEDULES
from app.core.postgres import (
    admin_audit_logs_table,
    analytics_snapshots_table,
    draw_schedules_table,
    get_engine,
    ingestion_runs_table,
    model_training_examples_table,
    model_versions_table,
    postgres_initialized,
    prediction_window_reviews_table,
    prediction_runs_table,
    results_table,
    users_table,
)
from app.services.schedule import utc_now


class DatabaseService:
    def __init__(self) -> None:
        self.pg_engine = get_engine()
        self._mock_results: dict[str, dict[str, Any]] = {}
        self._mock_users: dict[str, dict[str, Any]] = {}
        self._mock_ingestion_runs: dict[str, dict[str, Any]] = {}
        self._mock_schedules: dict[str, dict[str, Any]] = {}
        self._mock_analytics: dict[str, dict[str, Any]] = {}
        self._mock_prediction_runs: dict[str, dict[str, Any]] = {}
        self._mock_model_training_examples: dict[str, dict[str, Any]] = {}
        self._mock_model_versions: dict[str, dict[str, Any]] = {}
        self._mock_prediction_window_reviews: dict[str, dict[str, Any]] = {}
        self._mock_audit_logs: dict[str, dict[str, Any]] = {}
        self._results_cache: list[dict[str, Any]] | None = None
        self._results_cache_loaded_at: datetime | None = None
        self._users_cache: list[dict[str, Any]] | None = None
        self._ingestion_runs_cache: list[dict[str, Any]] | None = None
        self._audit_logs_cache: list[dict[str, Any]] | None = None
        self.ensure_default_schedules()

    @property
    def is_postgres_mode(self) -> bool:
        return bool(settings.use_postgres and postgres_initialized and self.pg_engine is not None)

    @property
    def is_mock_mode(self) -> bool:
        return not self.is_postgres_mode

    def reset_mock_state(self) -> None:
        self._mock_results = {}
        self._mock_users = {}
        self._mock_ingestion_runs = {}
        self._mock_schedules = {}
        self._mock_analytics = {}
        self._mock_prediction_runs = {}
        self._mock_model_training_examples = {}
        self._mock_model_versions = {}
        self._mock_prediction_window_reviews = {}
        self._mock_audit_logs = {}
        self._results_cache = None
        self._results_cache_loaded_at = None
        self._users_cache = None
        self._ingestion_runs_cache = None
        self._audit_logs_cache = None
        self.ensure_default_schedules()

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        if hasattr(row, "_mapping"):
            return dict(row._mapping)
        return dict(row)

    def _prepare_for_storage(self, value):
        if isinstance(value, dict):
            return {key: self._prepare_for_storage(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._prepare_for_storage(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _coerce_date_arg(value: str | date | None) -> date | None:
        if value is None or isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def _should_allow_postgres_fallback(self) -> bool:
        return not settings.use_postgres

    def ensure_default_schedules(self) -> None:
        schedules = [deepcopy(entry) for entry in DEFAULT_DRAW_SCHEDULES]
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    for schedule in schedules:
                        statement = pg_insert(draw_schedules_table).values(**schedule).on_conflict_do_nothing(
                            index_elements=[draw_schedules_table.c.canonical_lottery_name]
                        )
                        connection.execute(statement)
                return
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        for schedule in schedules:
            self._mock_schedules[schedule["canonical_lottery_name"]] = schedule

    def get_schedules(self) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    rows = connection.execute(
                        select(draw_schedules_table).order_by(draw_schedules_table.c.canonical_lottery_name)
                    ).mappings()
                    return [self._row_to_dict(row) for row in rows]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        if not self._mock_schedules:
            for schedule in DEFAULT_DRAW_SCHEDULES:
                self._mock_schedules[schedule["canonical_lottery_name"]] = deepcopy(schedule)
        return sorted(
            deepcopy(list(self._mock_schedules.values())),
            key=lambda item: item["canonical_lottery_name"],
        )

    def save_user(self, user_data: dict[str, Any]) -> str:
        payload = deepcopy(user_data)
        payload.setdefault("created_at", utc_now())
        payload.setdefault("is_active", True)
        payload.setdefault("role", "user")
        payload.setdefault("must_change_password", False)
        payload.setdefault("password_changed_at", utc_now() if not payload.get("must_change_password") else None)

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    insert_stmt = pg_insert(users_table).values(**payload)
                    connection.execute(
                        insert_stmt.on_conflict_do_update(
                            index_elements=[users_table.c.username],
                            set_={
                                "email": insert_stmt.excluded.email,
                                "full_name": insert_stmt.excluded.full_name,
                                "password": insert_stmt.excluded.password,
                                "role": insert_stmt.excluded.role,
                                "is_active": insert_stmt.excluded.is_active,
                                "created_at": insert_stmt.excluded.created_at,
                                "must_change_password": insert_stmt.excluded.must_change_password,
                                "password_changed_at": insert_stmt.excluded.password_changed_at,
                            },
                        )
                    )
                    self._users_cache = None
                    return payload["username"]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_users[payload["username"]] = payload
        return payload["username"]

    def get_user(self, username: str) -> dict[str, Any] | None:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    row = connection.execute(
                        select(users_table).where(users_table.c.username == username)
                    ).mappings().first()
                    return self._row_to_dict(row) if row else None
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        user = self._mock_users.get(username)
        return deepcopy(user) if user else None

    def update_user(self, username: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_user(username)
        if not existing:
            return None

        payload = deepcopy(existing)
        payload.update(deepcopy(updates))
        self.save_user(payload)
        return deepcopy(payload)

    def list_users(self, limit: int | None = 100) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(users_table).order_by(users_table.c.created_at.desc())
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    users = [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
                    self._users_cache = deepcopy(users)
                    return users
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None
                if self._users_cache is not None:
                    return deepcopy(self._users_cache[:limit] if limit and limit > 0 else self._users_cache)

        users = list(self._mock_users.values())

        users.sort(key=lambda item: item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(users)
        return deepcopy(users[:limit])

    def upsert_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        inserted = []
        duplicates = []

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    for result in results:
                        statement = (
                            pg_insert(results_table)
                            .values(**deepcopy(result))
                            .on_conflict_do_nothing(index_elements=[results_table.c.dedupe_key])
                            .returning(results_table.c.dedupe_key)
                        )
                        inserted_key = connection.execute(statement).scalar_one_or_none()
                        if inserted_key:
                            inserted.append(deepcopy(result))
                        else:
                            duplicates.append(result["dedupe_key"])
                self._results_cache = None
                self._results_cache_loaded_at = None
                return {
                    "new_results": inserted,
                    "new_count": len(inserted),
                    "duplicate_count": len(duplicates),
                    "duplicate_keys": duplicates,
                }
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        for result in results:
            dedupe_key = result["dedupe_key"]
            if dedupe_key in self._mock_results:
                duplicates.append(dedupe_key)
                continue
            self._mock_results[dedupe_key] = deepcopy(result)
            inserted.append(deepcopy(result))

        self._results_cache = None
        self._results_cache_loaded_at = None
        return {
            "new_results": inserted,
            "new_count": len(inserted),
            "duplicate_count": len(duplicates),
            "duplicate_keys": duplicates,
        }

    def _get_cached_results(self) -> list[dict[str, Any]] | None:
        if self._results_cache is None or self._results_cache_loaded_at is None:
            return None
        if utc_now() - self._results_cache_loaded_at > timedelta(seconds=settings.results_cache_ttl_seconds):
            return None
        return deepcopy(self._results_cache)

    def _set_cached_results(self, results: list[dict[str, Any]]) -> None:
        self._results_cache = deepcopy(results)
        self._results_cache_loaded_at = utc_now()

    def _load_all_results(self) -> list[dict[str, Any]]:
        cached = self._get_cached_results()
        if cached is not None:
            return cached

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    results = [self._row_to_dict(row) for row in connection.execute(select(results_table)).mappings()]
                    self._set_cached_results(results)
                    return deepcopy(results)
            except Exception:
                if not self._should_allow_postgres_fallback():
                    if self._results_cache is not None:
                        return deepcopy(self._results_cache)
                    raise
                self.pg_engine = None
                if self._results_cache is not None:
                    return deepcopy(self._results_cache)
                raise

        results = list(self._mock_results.values())
        self._set_cached_results(results)
        return deepcopy(results)

    def get_results(
        self,
        canonical_lottery_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        draw_time_local: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        results = self._load_all_results() if not self.is_mock_mode else list(self._mock_results.values())

        filtered = []
        for result in results:
            draw_date = result.get("draw_date")
            if isinstance(draw_date, datetime):
                draw_date = draw_date.date().isoformat()
            elif hasattr(draw_date, "isoformat") and not isinstance(draw_date, str):
                draw_date = draw_date.isoformat()

            result = deepcopy(result)
            result["draw_date"] = draw_date

            if canonical_lottery_name and result.get("canonical_lottery_name") != canonical_lottery_name:
                continue
            if start_date and draw_date and draw_date < start_date:
                continue
            if end_date and draw_date and draw_date > end_date:
                continue
            if draw_time_local and result.get("draw_time_local") != draw_time_local:
                continue
            filtered.append(result)

        filtered.sort(
            key=lambda item: item.get("draw_datetime_utc") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        if limit is None or limit <= 0:
            return filtered
        return filtered[:limit]

    def save_ingestion_run(self, run_data: dict[str, Any]) -> str:
        payload = deepcopy(run_data)
        payload.setdefault("id", payload.get("id") or str(uuid4()))
        json_ready = deepcopy(payload)
        for key in ("errors", "source_urls", "lotteries_seen", "missing_slots", "source_status", "source_reports"):
            json_ready[key] = self._prepare_for_storage(json_ready.get(key, [] if key.endswith("s") else {}))

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    insert_stmt = pg_insert(ingestion_runs_table).values(**json_ready)
                    connection.execute(
                        insert_stmt.on_conflict_do_update(
                            index_elements=[ingestion_runs_table.c.id],
                            set_={
                                "trigger": insert_stmt.excluded.trigger,
                                "status": insert_stmt.excluded.status,
                                "started_at": insert_stmt.excluded.started_at,
                                "completed_at": insert_stmt.excluded.completed_at,
                                "duration_seconds": insert_stmt.excluded.duration_seconds,
                                "results_found": insert_stmt.excluded.results_found,
                                "new_results": insert_stmt.excluded.new_results,
                                "duplicates": insert_stmt.excluded.duplicates,
                                "errors": insert_stmt.excluded.errors,
                                "source_urls": insert_stmt.excluded.source_urls,
                                "lotteries_seen": insert_stmt.excluded.lotteries_seen,
                                "coverage_start": insert_stmt.excluded.coverage_start,
                                "coverage_end": insert_stmt.excluded.coverage_end,
                                "parser_version": insert_stmt.excluded.parser_version,
                                "missing_slots": insert_stmt.excluded.missing_slots,
                                "source_status": insert_stmt.excluded.source_status,
                                "source_reports": insert_stmt.excluded.source_reports,
                            },
                        )
                    )
                    self._ingestion_runs_cache = None
                    return payload["id"]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_ingestion_runs[payload["id"]] = payload
        return payload["id"]

    def get_latest_ingestion_run(self) -> dict[str, Any] | None:
        runs = self.get_ingestion_runs(limit=None)
        if not runs:
            return None
        return deepcopy(runs[0])

    def get_ingestion_runs(
        self,
        limit: int | None = 50,
        trigger_contains: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(ingestion_runs_table)
                    if trigger_contains:
                        statement = statement.where(ingestion_runs_table.c.trigger.contains(trigger_contains))
                    if status:
                        statement = statement.where(ingestion_runs_table.c.status == status)
                    statement = statement.order_by(ingestion_runs_table.c.completed_at.desc())
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    runs = [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
                    self._ingestion_runs_cache = deepcopy(runs)
                    return runs
            except Exception:
                if not self._should_allow_postgres_fallback():
                    if self._ingestion_runs_cache is not None:
                        cached = deepcopy(self._ingestion_runs_cache)
                        if trigger_contains:
                            cached = [item for item in cached if trigger_contains in item.get("trigger", "")]
                        if status:
                            cached = [item for item in cached if item.get("status") == status]
                        return cached[:limit] if limit and limit > 0 else cached
                    raise
                self.pg_engine = None
                if self._ingestion_runs_cache is not None:
                    cached = deepcopy(self._ingestion_runs_cache)
                    if trigger_contains:
                        cached = [item for item in cached if trigger_contains in item.get("trigger", "")]
                    if status:
                        cached = [item for item in cached if item.get("status") == status]
                    return cached[:limit] if limit and limit > 0 else cached

        runs = list(self._mock_ingestion_runs.values())

        if trigger_contains:
            runs = [item for item in runs if trigger_contains in item.get("trigger", "")]
        if status:
            runs = [item for item in runs if item.get("status") == status]

        runs.sort(key=lambda item: item.get("completed_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(runs)
        return deepcopy(runs[:limit])

    def get_latest_backfill_run(self) -> dict[str, Any] | None:
        runs = self.get_ingestion_runs(limit=1, trigger_contains="backfill")
        return runs[0] if runs else None

    def save_analytics_snapshot(self, snapshot_key: str, snapshot: dict[str, Any]) -> str:
        payload = deepcopy(snapshot)
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    insert_stmt = pg_insert(analytics_snapshots_table).values(
                        snapshot_key=snapshot_key,
                        generated_at=payload.get("generated_at"),
                        payload=self._prepare_for_storage(payload),
                    )
                    connection.execute(
                        insert_stmt.on_conflict_do_update(
                            index_elements=[analytics_snapshots_table.c.snapshot_key],
                            set_={
                                "generated_at": insert_stmt.excluded.generated_at,
                                "payload": insert_stmt.excluded.payload,
                            },
                        )
                    )
                    return snapshot_key
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_analytics[snapshot_key] = payload
        return snapshot_key

    def get_analytics_snapshot(self, snapshot_key: str) -> dict[str, Any] | None:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    row = connection.execute(
                        select(analytics_snapshots_table.c.payload).where(analytics_snapshots_table.c.snapshot_key == snapshot_key)
                    ).first()
                    return deepcopy(row[0]) if row else None
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        snapshot = self._mock_analytics.get(snapshot_key)
        return deepcopy(snapshot) if snapshot else None

    def get_latest_analytics_snapshot(self, snapshot_prefix: str | None = None) -> dict[str, Any] | None:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(analytics_snapshots_table.c.payload).order_by(
                        analytics_snapshots_table.c.generated_at.desc()
                    )
                    if snapshot_prefix:
                        statement = statement.where(analytics_snapshots_table.c.snapshot_key.startswith(snapshot_prefix))
                    row = connection.execute(statement.limit(1)).first()
                    return deepcopy(row[0]) if row else None
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        keys = list(self._mock_analytics.keys())
        if snapshot_prefix:
            keys = [key for key in keys if key.startswith(snapshot_prefix)]
        if not keys:
            return None
        key = sorted(keys)[-1]
        return deepcopy(self._mock_analytics[key])

    def save_prediction_run(self, payload: dict[str, Any]) -> str:
        data = deepcopy(payload)
        data.setdefault("id", data.get("id") or str(uuid4()))
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    connection.execute(
                        pg_insert(prediction_runs_table).values(
                            id=data["id"],
                            generated_at=data.get("generated_at"),
                            delivery_status=data.get("delivery_status"),
                            preview_only=data.get("preview_only", False),
                            target_lotteries=data.get("target_lotteries", []),
                            top_n=data.get("top_n"),
                            summary=self._prepare_for_storage(data.get("summary", {})),
                            telegram_sent=data.get("telegram_sent", False),
                        )
                    )
                    return data["id"]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_prediction_runs[data["id"]] = data
        return data["id"]

    def get_prediction_runs(self, limit: int | None = 25) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(prediction_runs_table).order_by(prediction_runs_table.c.generated_at.desc())
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    return [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        runs = list(self._mock_prediction_runs.values())

        runs.sort(key=lambda item: item.get("generated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(runs)
        return deepcopy(runs[:limit])

    def get_latest_prediction_run(self) -> dict[str, Any] | None:
        runs = self.get_prediction_runs(limit=1)
        return runs[0] if runs else None

    def save_model_training_examples(self, examples: list[dict[str, Any]]) -> int:
        stored = 0
        if not examples:
            return stored

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    for example in examples:
                        payload = deepcopy(example)
                        insert_stmt = pg_insert(model_training_examples_table).values(
                            example_key=payload["example_key"],
                            segment_key=payload["segment_key"],
                            canonical_lottery_name=payload["canonical_lottery_name"],
                            draw_date=payload["draw_date"],
                            draw_time_local=payload["draw_time_local"],
                            animal_number=payload["animal_number"],
                            label_hit=payload["label_hit"],
                            methodology_version=payload["methodology_version"],
                            generated_at=payload["generated_at"],
                            features=self._prepare_for_storage(payload.get("features", {})),
                            metadata=self._prepare_for_storage(payload.get("metadata", {})),
                        )
                        connection.execute(
                            insert_stmt.on_conflict_do_update(
                                index_elements=[model_training_examples_table.c.example_key],
                                set_={
                                    "segment_key": insert_stmt.excluded.segment_key,
                                    "canonical_lottery_name": insert_stmt.excluded.canonical_lottery_name,
                                    "draw_date": insert_stmt.excluded.draw_date,
                                    "draw_time_local": insert_stmt.excluded.draw_time_local,
                                    "animal_number": insert_stmt.excluded.animal_number,
                                    "label_hit": insert_stmt.excluded.label_hit,
                                    "methodology_version": insert_stmt.excluded.methodology_version,
                                    "generated_at": insert_stmt.excluded.generated_at,
                                    "features": insert_stmt.excluded.features,
                                    "metadata": insert_stmt.excluded.metadata,
                                },
                            )
                        )
                        stored += 1
                return stored
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        for example in examples:
            self._mock_model_training_examples[example["example_key"]] = deepcopy(example)
            stored += 1
        return stored

    def get_model_training_examples(
        self,
        *,
        segment_key: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(model_training_examples_table)
                    if segment_key:
                        statement = statement.where(model_training_examples_table.c.segment_key == segment_key)
                    if start_date:
                        statement = statement.where(
                            model_training_examples_table.c.draw_date >= self._coerce_date_arg(start_date)
                        )
                    if end_date:
                        statement = statement.where(
                            model_training_examples_table.c.draw_date <= self._coerce_date_arg(end_date)
                        )
                    statement = statement.order_by(
                        model_training_examples_table.c.draw_date.desc(),
                        model_training_examples_table.c.draw_time_local.desc(),
                    )
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    return [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        examples = list(self._mock_model_training_examples.values())

        filtered = []
        for example in examples:
            example_date = example.get("draw_date")
            if hasattr(example_date, "isoformat") and not isinstance(example_date, str):
                example_date = example_date.isoformat()
            if segment_key and example.get("segment_key") != segment_key:
                continue
            if start_date and example_date and example_date < start_date:
                continue
            if end_date and example_date and example_date > end_date:
                continue
            filtered.append(deepcopy(example))

        filtered.sort(key=lambda item: (item.get("draw_date"), item.get("draw_time_local")), reverse=True)
        if limit is None or limit <= 0:
            return filtered
        return filtered[:limit]

    def save_model_version(self, payload: dict[str, Any]) -> str:
        data = deepcopy(payload)
        data.setdefault("model_key", data.get("model_key") or str(uuid4()))
        data.setdefault("notes", [])
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    insert_stmt = pg_insert(model_versions_table).values(
                        model_key=data["model_key"],
                        segment_key=data["segment_key"],
                        status=data["status"],
                        trained_at=data["trained_at"],
                        training_start_date=data.get("training_start_date"),
                        training_end_date=data.get("training_end_date"),
                        ensemble_weights=self._prepare_for_storage(data.get("ensemble_weights", {})),
                        validation_metrics=self._prepare_for_storage(data.get("validation_metrics", {})),
                        calibration_method=data.get("calibration_method"),
                        artifact=self._prepare_for_storage(data.get("artifact", {})),
                        notes=self._prepare_for_storage(data.get("notes", [])),
                    )
                    connection.execute(
                        insert_stmt.on_conflict_do_update(
                            index_elements=[model_versions_table.c.model_key],
                            set_={
                                "segment_key": insert_stmt.excluded.segment_key,
                                "status": insert_stmt.excluded.status,
                                "trained_at": insert_stmt.excluded.trained_at,
                                "training_start_date": insert_stmt.excluded.training_start_date,
                                "training_end_date": insert_stmt.excluded.training_end_date,
                                "ensemble_weights": insert_stmt.excluded.ensemble_weights,
                                "validation_metrics": insert_stmt.excluded.validation_metrics,
                                "calibration_method": insert_stmt.excluded.calibration_method,
                                "artifact": insert_stmt.excluded.artifact,
                                "notes": insert_stmt.excluded.notes,
                            },
                        )
                    )
                    return data["model_key"]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_model_versions[data["model_key"]] = data
        return data["model_key"]

    def get_model_versions(
        self,
        *,
        segment_key: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(model_versions_table)
                    if segment_key:
                        statement = statement.where(model_versions_table.c.segment_key == segment_key)
                    if status:
                        statement = statement.where(model_versions_table.c.status == status)
                    statement = statement.order_by(model_versions_table.c.trained_at.desc())
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    return [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        models = list(self._mock_model_versions.values())

        if segment_key:
            models = [item for item in models if item.get("segment_key") == segment_key]
        if status:
            models = [item for item in models if item.get("status") == status]
        models.sort(key=lambda item: item.get("trained_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(models)
        return deepcopy(models[:limit])

    def get_champion_model(self, segment_key: str) -> dict[str, Any] | None:
        models = self.get_model_versions(segment_key=segment_key, status="champion", limit=1)
        return models[0] if models else None

    def save_prediction_window_reviews(self, reviews: list[dict[str, Any]]) -> int:
        stored = 0
        if not reviews:
            return stored

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    for review in reviews:
                        payload = deepcopy(review)
                        insert_stmt = pg_insert(prediction_window_reviews_table).values(
                            review_key=payload["review_key"],
                            segment_key=payload["segment_key"],
                            canonical_lottery_name=payload["canonical_lottery_name"],
                            draw_date=payload["draw_date"],
                            draw_time_local=payload["draw_time_local"],
                            actual_animal_number=payload["actual_animal_number"],
                            actual_animal_name=payload["actual_animal_name"],
                            predicted_at=payload.get("predicted_at"),
                            model_key=payload.get("model_key"),
                            ensemble_version=payload.get("ensemble_version"),
                            lead_signal_key=payload.get("lead_signal_key"),
                            confidence_band=payload.get("confidence_band"),
                            stability_score=payload.get("stability_score"),
                            hit_top_1=payload.get("hit_top_1", False),
                            hit_top_3=payload.get("hit_top_3", False),
                            hit_top_5=payload.get("hit_top_5", False),
                            payload=self._prepare_for_storage(payload.get("payload", {})),
                        )
                        connection.execute(
                            insert_stmt.on_conflict_do_update(
                                index_elements=[prediction_window_reviews_table.c.review_key],
                                set_={
                                    "segment_key": insert_stmt.excluded.segment_key,
                                    "canonical_lottery_name": insert_stmt.excluded.canonical_lottery_name,
                                    "draw_date": insert_stmt.excluded.draw_date,
                                    "draw_time_local": insert_stmt.excluded.draw_time_local,
                                    "actual_animal_number": insert_stmt.excluded.actual_animal_number,
                                    "actual_animal_name": insert_stmt.excluded.actual_animal_name,
                                    "predicted_at": insert_stmt.excluded.predicted_at,
                                    "model_key": insert_stmt.excluded.model_key,
                                    "ensemble_version": insert_stmt.excluded.ensemble_version,
                                    "lead_signal_key": insert_stmt.excluded.lead_signal_key,
                                    "confidence_band": insert_stmt.excluded.confidence_band,
                                    "stability_score": insert_stmt.excluded.stability_score,
                                    "hit_top_1": insert_stmt.excluded.hit_top_1,
                                    "hit_top_3": insert_stmt.excluded.hit_top_3,
                                    "hit_top_5": insert_stmt.excluded.hit_top_5,
                                    "payload": insert_stmt.excluded.payload,
                                },
                            )
                        )
                        stored += 1
                return stored
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        for review in reviews:
            self._mock_prediction_window_reviews[review["review_key"]] = deepcopy(review)
            stored += 1
        return stored

    def get_prediction_window_reviews(
        self,
        *,
        segment_key: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(prediction_window_reviews_table)
                    if segment_key:
                        statement = statement.where(prediction_window_reviews_table.c.segment_key == segment_key)
                    if start_date:
                        statement = statement.where(
                            prediction_window_reviews_table.c.draw_date >= self._coerce_date_arg(start_date)
                        )
                    if end_date:
                        statement = statement.where(
                            prediction_window_reviews_table.c.draw_date <= self._coerce_date_arg(end_date)
                        )
                    statement = statement.order_by(
                        prediction_window_reviews_table.c.draw_date.desc(),
                        prediction_window_reviews_table.c.draw_time_local.desc(),
                    )
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    return [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        reviews = list(self._mock_prediction_window_reviews.values())

        filtered = []
        for review in reviews:
            review_date = review.get("draw_date")
            if hasattr(review_date, "isoformat") and not isinstance(review_date, str):
                review_date = review_date.isoformat()
            if segment_key and review.get("segment_key") != segment_key:
                continue
            if start_date and review_date and review_date < start_date:
                continue
            if end_date and review_date and review_date > end_date:
                continue
            filtered.append(deepcopy(review))

        filtered.sort(key=lambda item: (item.get("draw_date"), item.get("draw_time_local")), reverse=True)
        if limit is None or limit <= 0:
            return filtered
        return filtered[:limit]

    def save_audit_log(self, payload: dict[str, Any]) -> str:
        data = deepcopy(payload)
        data.setdefault("created_at", utc_now())
        data.setdefault("id", data.get("id") or str(uuid4()))

        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    connection.execute(
                        pg_insert(admin_audit_logs_table).values(
                            id=data["id"],
                            action=data.get("action"),
                            actor_username=data.get("actor_username"),
                            actor_role=data.get("actor_role"),
                            status=data.get("status"),
                            source_ip=data.get("source_ip"),
                            created_at=data.get("created_at"),
                            details=self._prepare_for_storage(data.get("details", {})),
                        )
                    )
                    self._audit_logs_cache = None
                    return data["id"]
            except Exception:
                if not self._should_allow_postgres_fallback():
                    raise
                self.pg_engine = None

        self._mock_audit_logs[data["id"]] = data
        return data["id"]

    def get_audit_logs(self, limit: int | None = 50) -> list[dict[str, Any]]:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    statement = select(admin_audit_logs_table).order_by(admin_audit_logs_table.c.created_at.desc())
                    if limit and limit > 0:
                        statement = statement.limit(limit)
                    logs = [self._row_to_dict(row) for row in connection.execute(statement).mappings()]
                    self._audit_logs_cache = deepcopy(logs)
                    return logs
            except Exception:
                if not self._should_allow_postgres_fallback():
                    if self._audit_logs_cache is not None:
                        return deepcopy(self._audit_logs_cache[:limit] if limit and limit > 0 else self._audit_logs_cache)
                    raise
                self.pg_engine = None
                if self._audit_logs_cache is not None:
                    return deepcopy(self._audit_logs_cache[:limit] if limit and limit > 0 else self._audit_logs_cache)

        logs = list(self._mock_audit_logs.values())

        logs.sort(key=lambda item: item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(logs)
        return deepcopy(logs[:limit])

    def count_results(self) -> int:
        if self.is_postgres_mode:
            try:
                with self.pg_engine.begin() as connection:
                    return int(connection.execute(select(func.count()).select_from(results_table)).scalar_one())
            except Exception:
                if not self._should_allow_postgres_fallback():
                    cached = self._results_cache if self._results_cache is not None else []
                    if cached:
                        return len(cached)
                    raise
                self.pg_engine = None
                cached = self._results_cache if self._results_cache is not None else []
                return len(cached)

        return len(self._mock_results)


db_service = DatabaseService()
