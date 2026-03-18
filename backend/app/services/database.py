from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from firebase_admin import firestore
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.firebase import firebase_initialized, get_db
from app.core.lottery_catalog import DEFAULT_DRAW_SCHEDULES
from app.core.postgres import (
    admin_audit_logs_table,
    analytics_snapshots_table,
    draw_schedules_table,
    get_engine,
    ingestion_runs_table,
    postgres_initialized,
    prediction_runs_table,
    results_table,
    users_table,
)
from app.services.schedule import utc_now


class DatabaseService:
    def __init__(self) -> None:
        self.db = get_db()
        self.pg_engine = get_engine()
        self._mock_results: dict[str, dict[str, Any]] = {}
        self._mock_users: dict[str, dict[str, Any]] = {}
        self._mock_ingestion_runs: dict[str, dict[str, Any]] = {}
        self._mock_schedules: dict[str, dict[str, Any]] = {}
        self._mock_analytics: dict[str, dict[str, Any]] = {}
        self._mock_prediction_runs: dict[str, dict[str, Any]] = {}
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
    def is_firestore_mode(self) -> bool:
        return bool(not self.is_postgres_mode and settings.use_firebase and firebase_initialized and self.db is not None)

    @property
    def is_mock_mode(self) -> bool:
        return not self.is_postgres_mode and not self.is_firestore_mode

    def reset_mock_state(self) -> None:
        self._mock_results = {}
        self._mock_users = {}
        self._mock_ingestion_runs = {}
        self._mock_schedules = {}
        self._mock_analytics = {}
        self._mock_prediction_runs = {}
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
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        return value

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
                self.pg_engine = None

        if self.is_firestore_mode:
            try:
                collection = self.db.collection("draw_schedules")
                for schedule in schedules:
                    doc_ref = collection.document(schedule["canonical_lottery_name"])
                    if not doc_ref.get().exists:
                        doc_ref.set(schedule)
                return
            except Exception:
                self.db = None

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
                self.pg_engine = None

        if self.is_firestore_mode:
            try:
                docs = self.db.collection("draw_schedules").stream()
                schedules = [doc.to_dict() for doc in docs]
                return sorted(schedules, key=lambda item: item["canonical_lottery_name"])
            except Exception:
                self.db = None

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc_ref = self.db.collection("users").document(payload["username"])
            doc_ref.set(self._prepare_for_storage(payload))
            self._users_cache = None
            return doc_ref.id

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc = self.db.collection("users").document(username).get()
            if not doc.exists:
                return None
            return doc.to_dict()

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
                self.pg_engine = None
                if self._users_cache is not None:
                    return deepcopy(self._users_cache[:limit] if limit and limit > 0 else self._users_cache)

        if self.is_firestore_mode:
            try:
                users = [doc.to_dict() for doc in self.db.collection("users").stream()]
                self._users_cache = deepcopy(users)
            except Exception:
                users = deepcopy(self._users_cache) if self._users_cache is not None else []
        else:
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
                self.pg_engine = None

        for result in results:
            dedupe_key = result["dedupe_key"]
            if self.is_firestore_mode:
                doc_ref = self.db.collection("results").document(dedupe_key)
                if doc_ref.get().exists:
                    duplicates.append(dedupe_key)
                    continue
                doc_ref.set(self._prepare_for_storage(result))
                inserted.append(result)
                continue

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
                self.pg_engine = None
                if self._results_cache is not None:
                    return deepcopy(self._results_cache)
                raise

        if self.is_firestore_mode:
            docs = self.db.collection("results").stream()
            results = [doc.to_dict() for doc in docs]
            self._set_cached_results(results)
            return deepcopy(results)

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc_ref = self.db.collection("ingestion_runs").document(payload["id"])
            doc_ref.set(self._prepare_for_storage(json_ready))
            self._ingestion_runs_cache = None
            return doc_ref.id

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
                self.pg_engine = None
                if self._ingestion_runs_cache is not None:
                    cached = deepcopy(self._ingestion_runs_cache)
                    if trigger_contains:
                        cached = [item for item in cached if trigger_contains in item.get("trigger", "")]
                    if status:
                        cached = [item for item in cached if item.get("status") == status]
                    return cached[:limit] if limit and limit > 0 else cached

        if self.is_firestore_mode:
            try:
                runs = [doc.to_dict() for doc in self.db.collection("ingestion_runs").stream()]
                self._ingestion_runs_cache = deepcopy(runs)
            except Exception:
                runs = deepcopy(self._ingestion_runs_cache) if self._ingestion_runs_cache is not None else []
        else:
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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc_ref = self.db.collection("analytics_snapshots").document(snapshot_key)
            doc_ref.set(self._prepare_for_storage(payload))
            return doc_ref.id

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc = self.db.collection("analytics_snapshots").document(snapshot_key).get()
            if not doc.exists:
                return None
            return doc.to_dict()

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
                self.pg_engine = None

        if self.is_firestore_mode:
            docs = []
            for doc in self.db.collection("analytics_snapshots").stream():
                if snapshot_prefix and not doc.id.startswith(snapshot_prefix):
                    continue
                docs.append(doc.to_dict())
            if not docs:
                return None
            docs.sort(key=lambda item: item.get("generated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return docs[0]

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc_ref = self.db.collection("prediction_runs").document(data["id"])
            doc_ref.set(self._prepare_for_storage(data))
            return doc_ref.id

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
                self.pg_engine = None

        if self.is_firestore_mode:
            runs = [doc.to_dict() for doc in self.db.collection("prediction_runs").stream()]
        else:
            runs = list(self._mock_prediction_runs.values())

        runs.sort(key=lambda item: item.get("generated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is None or limit <= 0:
            return deepcopy(runs)
        return deepcopy(runs[:limit])

    def get_latest_prediction_run(self) -> dict[str, Any] | None:
        runs = self.get_prediction_runs(limit=1)
        return runs[0] if runs else None

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
                self.pg_engine = None

        if self.is_firestore_mode:
            doc_ref = self.db.collection("admin_audit_logs").document(data["id"])
            doc_ref.set(self._prepare_for_storage(data))
            self._audit_logs_cache = None
            return doc_ref.id

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
                self.pg_engine = None
                if self._audit_logs_cache is not None:
                    return deepcopy(self._audit_logs_cache[:limit] if limit and limit > 0 else self._audit_logs_cache)

        if self.is_firestore_mode:
            try:
                logs = [doc.to_dict() for doc in self.db.collection("admin_audit_logs").stream()]
                self._audit_logs_cache = deepcopy(logs)
            except Exception:
                logs = deepcopy(self._audit_logs_cache) if self._audit_logs_cache is not None else []
        else:
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
                self.pg_engine = None
                cached = self._results_cache if self._results_cache is not None else []
                return len(cached)

        if self.is_firestore_mode:
            try:
                aggregate = self.db.collection("results").count().get()
                return aggregate[0][0].value if aggregate else 0
            except Exception:
                cached = self._results_cache if self._results_cache is not None else []
                return len(cached)

        return len(self._mock_results)


db_service = DatabaseService()
