from datetime import date, datetime, timedelta, timezone

from app.core.runtime import register_startup_issue
from app.services.database import db_service
from app.services.schedule import local_now


def make_result(draw_date: date, draw_time_local: str, number: int, lottery_name: str):
    slug = lottery_name.lower().replace(" ", "-")
    return {
        "canonical_lottery_name": lottery_name,
        "source_lottery_name": lottery_name,
        "draw_date": draw_date,
        "draw_time_local": draw_time_local,
        "draw_datetime_utc": datetime.strptime(
            f"{draw_date.isoformat()}T{draw_time_local}:00+0000",
            "%Y-%m-%dT%H:%M:%S%z",
        ).astimezone(timezone.utc),
        "animal_number": number,
        "animal_name": "Prueba",
        "source_url": "https://example.com",
        "status": "confirmed",
        "dedupe_key": f"{slug}:{draw_date.isoformat()}:{draw_time_local}:{number:02d}",
        "ingested_at": datetime(2026, 3, 18, tzinfo=timezone.utc),
        "source_page": "animalitos",
    }


def test_protected_routes_require_authentication(client):
    response = client.get("/api/dashboard/overview")
    assert response.status_code in {401, 403}


def test_ping_route_is_public(client):
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_route_reports_degraded_mode_when_database_is_unavailable(client, monkeypatch):
    register_startup_issue("database", "Supabase/Postgres no estuvo disponible durante el arranque.")
    monkeypatch.setattr(
        "app.main.runtime_status_snapshot",
        lambda: {
            "database_required": True,
            "database_connected": False,
            "degraded": True,
            "startup_issues": [
                {
                    "component": "database",
                    "message": "Supabase/Postgres no estuvo disponible durante el arranque.",
                }
            ],
        },
    )

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["startup_issues"][0]["component"] == "database"


def test_protected_routes_return_503_when_database_is_unavailable(client, monkeypatch):
    monkeypatch.setattr("app.core.runtime.database_operational", lambda: False)

    login_response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    overview_response = client.get(
        "/api/dashboard/overview",
        headers={"Authorization": "Bearer fake-token"},
    )

    assert login_response.status_code == 503
    assert overview_response.status_code == 503


def test_register_forces_regular_user_role(client):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "visitante",
            "email": "visitante@example.com",
            "password": "ClaveSegura123",
            "role": "admin",
        },
    )

    assert response.status_code == 201
    assert response.json()["role"] == "user"
    assert response.json()["must_change_password"] is False
    assert response.json()["created_at"] is not None
    assert response.json()["password_changed_at"] is not None


def test_dashboard_and_history_routes(client, admin_headers):
    today = local_now().date()
    yesterday = today - timedelta(days=1)
    db_service.upsert_results(
        [
            make_result(today, "08:00", 33, "Lotto Activo"),
            make_result(today, "09:00", 25, "La Granjita"),
            make_result(yesterday, "08:00", 7, "Lotto Activo Internacional"),
        ]
    )

    overview_response = client.get("/api/dashboard/overview", headers=admin_headers)
    history_response = client.get(
        "/api/results/history",
        headers=admin_headers,
        params={"lottery_name": "Lotto Activo", "start_date": today.isoformat(), "end_date": today.isoformat()},
    )

    assert overview_response.status_code == 200
    assert history_response.status_code == 200

    overview_payload = overview_response.json()
    history_payload = history_response.json()

    assert overview_payload["total_results_today"] >= 2
    assert any(item["canonical_lottery_name"] == "Lotto Activo" for item in overview_payload["primary_lotteries"])
    assert all("next_draw" in item for item in overview_payload["primary_lotteries"])
    assert history_payload["total"] == 1
    assert history_payload["items"][0]["animal_number"] == 33


def test_possible_results_preview_and_telegram_dispatch(client, admin_headers, monkeypatch):
    today = local_now().date()
    db_service.upsert_results(
        [
            make_result(today, "08:00", 12, "Lotto Activo"),
            make_result(today, "09:00", 12, "Lotto Activo"),
            make_result(today, "10:00", 25, "La Granjita"),
            make_result(today - timedelta(days=1), "08:00", 12, "Lotto Activo"),
            make_result(today - timedelta(days=2), "08:00", 33, "Lotto Activo Internacional"),
        ]
    )

    sent_payload = {}

    async def fake_send(summary):
        sent_payload["summary"] = summary
        return True

    monkeypatch.setattr(
        "app.services.monitoring.telegram_service.send_possible_results_summary",
        fake_send,
    )

    preview_response = client.get("/api/analytics/possible-results", headers=admin_headers)
    telegram_response = client.post("/api/admin/telegram/possible-results", headers=admin_headers)

    assert preview_response.status_code == 200
    assert telegram_response.status_code == 200
    assert preview_response.json()["lotteries"]
    assert preview_response.json()["lotteries"][0]["draw_predictions"]
    first_candidate = preview_response.json()["lotteries"][0]["draw_predictions"][0]["candidates"][0]
    assert first_candidate["strongest_signals"]
    assert "model_probability" in first_candidate
    assert "rule_score" in first_candidate
    assert "external_prior" in first_candidate
    assert "ensemble_score" in first_candidate
    assert "confidence_band" in first_candidate
    assert "segment_key" in first_candidate
    assert telegram_response.json()["details"]["sent"] is True
    assert sent_payload["summary"]["lotteries"]


def test_admin_quality_status_audit_and_backtesting_routes(client, admin_headers):
    today = local_now().date()
    db_service.upsert_results(
        [
            make_result(today, "08:00", 12, "Lotto Activo"),
            make_result(today, "09:00", 21, "Lotto Activo"),
            make_result(today - timedelta(days=1), "08:00", 12, "Lotto Activo"),
            make_result(today - timedelta(days=2), "08:00", 33, "Lotto Activo"),
            make_result(today - timedelta(days=3), "08:00", 45, "Lotto Activo"),
            make_result(today - timedelta(days=4), "08:00", 12, "Lotto Activo"),
            make_result(today - timedelta(days=5), "08:00", 7, "Lotto Activo"),
            make_result(today - timedelta(days=6), "08:00", 12, "Lotto Activo"),
            make_result(today - timedelta(days=7), "08:00", 25, "Lotto Activo"),
            make_result(today - timedelta(days=8), "08:00", 12, "Lotto Activo"),
            make_result(today - timedelta(days=9), "08:00", 5, "Lotto Activo"),
            make_result(today - timedelta(days=10), "08:00", 9, "Lotto Activo"),
        ]
    )
    db_service.save_audit_log(
        {
            "action": "results_refresh",
            "actor_username": "admin",
            "actor_role": "admin",
            "status": "success",
            "source_ip": "127.0.0.1",
            "details": {"new_results": 2},
        }
    )

    quality_response = client.get("/api/admin/system/quality", headers=admin_headers, params={"days": 3})
    status_response = client.get("/api/admin/system/status", headers=admin_headers)
    audit_response = client.get("/api/admin/system/audit", headers=admin_headers, params={"limit": 10})
    backtesting_response = client.get("/api/analytics/backtesting", headers=admin_headers, params={"days": 30})

    assert quality_response.status_code == 200
    assert status_response.status_code == 200
    assert audit_response.status_code == 200
    assert backtesting_response.status_code == 200
    assert quality_response.json()["items"]
    assert "total_results" in status_response.json()
    assert "database_connected" in status_response.json()
    assert "scheduler_mode" in status_response.json()
    assert "scheduler_last_received_at" in status_response.json()
    assert audit_response.json()[0]["action"] == "results_refresh"
    assert "overall_top_3_rate" in backtesting_response.json()
    assert "calibration_summary" in backtesting_response.json()
    assert "weight_adjustments" in backtesting_response.json()


def test_model_health_route_returns_segment_rows(client, admin_headers, monkeypatch):
    generated_at = datetime(2026, 3, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_model_health_summary",
        lambda: {
            "generated_at": generated_at,
            "ensemble_version": "hybrid-ensemble-v1",
            "segments": [
                {
                    "segment_key": "lotto-activo-hourly",
                    "status": "champion",
                    "champion_model_key": "model-123",
                    "trained_at": generated_at,
                    "training_start_date": "2026-01-01",
                    "training_end_date": "2026-03-21",
                    "validation_top_1_rate": 0.1,
                    "validation_top_3_rate": 0.2,
                    "validation_top_5_rate": 0.3,
                    "baseline_top_3_rate": 0.18,
                    "baseline_top_5_rate": 0.27,
                    "calibration_method": "sigmoid",
                    "confidence_bands": [
                        {
                            "confidence_band": "alta",
                            "evaluated_draws": 10,
                            "hit_top_1_rate": 0.2,
                            "hit_top_3_rate": 0.4,
                            "hit_top_5_rate": 0.6,
                        }
                    ],
                    "notes": ["Champion vigente."],
                }
            ],
            "notes": ["OK"],
        },
    )

    response = client.get("/api/analytics/model-health", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["ensemble_version"] == "hybrid-ensemble-v1"
    assert response.json()["segments"][0]["segment_key"] == "lotto-activo-hourly"


def test_admin_background_backfill_status_routes(client, admin_headers, monkeypatch):
    async def fake_start_backfill(request, trigger="manual"):
        return (
            {
                "job_id": "job-123",
                "status": "queued",
                "trigger": "manual:backfill",
                "message": "Backfill en cola para ejecutarse en segundo plano.",
                "start_date": date(2026, 3, 1),
                "end_date": date(2026, 3, 7),
                "total_days": 7,
                "completed_days": 0,
                "current_date": date(2026, 3, 1),
                "results_found": 0,
                "new_results": 0,
                "duplicates": 0,
                "empty_days": [],
                "errors_count": 0,
                "last_error": None,
                "started_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
                "completed_at": None,
                "ingestion_run_id": None,
            },
            True,
        )

    monkeypatch.setattr("app.api.admin.monitoring_service.start_backfill", fake_start_backfill)
    monkeypatch.setattr(
        "app.api.admin.monitoring_service.get_backfill_status",
        lambda: {
            "job_id": "job-123",
            "status": "running",
            "trigger": "manual:backfill",
            "message": "Procesando 2026-03-01 (1/7)",
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 7),
            "total_days": 7,
            "completed_days": 1,
            "current_date": date(2026, 3, 1),
            "results_found": 12,
            "new_results": 10,
            "duplicates": 2,
            "empty_days": [],
            "errors_count": 0,
            "last_error": None,
            "started_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
            "completed_at": None,
            "ingestion_run_id": None,
        },
    )

    start_response = client.post(
        "/api/admin/backfill",
        headers=admin_headers,
        json={"start_date": "2026-03-01", "end_date": "2026-03-07"},
    )
    status_response = client.get("/api/admin/backfill/status", headers=admin_headers)

    assert start_response.status_code == 200
    assert start_response.json()["details"]["started"] is True
    assert start_response.json()["details"]["backfill"]["job_id"] == "job-123"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "running"
    assert status_response.json()["completed_days"] == 1


def test_internal_scheduler_refresh_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.settings.scheduler_service_token", "scheduler-test-token")

    async def fake_start_scheduler_refresh(trigger="cloud-scheduler", notify=True):
        return (
            {
                "job_id": "refresh-123",
                "status": "queued",
                "trigger": trigger,
                "message": "Refresh en cola para ejecutarse en segundo plano.",
                "results_found": 0,
                "new_results": 0,
                "duplicates": 0,
                "errors_count": 0,
                "last_error": None,
                "started_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
                "completed_at": None,
                "ingestion_run_id": None,
            },
            True,
        )

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_scheduler_refresh",
        fake_start_scheduler_refresh,
    )

    response = client.post(
        "/api/internal/scheduler/refresh",
        headers={"X-Scheduler-Token": "scheduler-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["details"]["job_id"] == "refresh-123"


def test_internal_scheduler_today_analysis_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.settings.scheduler_service_token", "scheduler-test-token")

    async def fake_start_today_analysis_report(phase="apertura", force_refresh=False):
        return (
            {
                "last_kind": "today-analysis",
                "last_status": "accepted",
                "last_trigger": f"scheduler-{phase}",
                "message": "Reporte operativo del dia programado en segundo plano.",
                "details": {
                    "job_id": "today-analysis-123",
                    "phase": phase,
                    "force_refresh": force_refresh,
                    "started": True,
                },
            },
            True,
        )

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_today_analysis_report",
        fake_start_today_analysis_report,
    )

    response = client.post(
        "/api/internal/scheduler/today-analysis?phase=apertura",
        headers={"X-Scheduler-Token": "scheduler-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["details"]["details"]["job_id"] == "today-analysis-123"


def test_internal_scheduler_daily_summary_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.settings.scheduler_service_token", "scheduler-test-token")

    async def fake_start_daily_summary_report():
        return (
            {
                "last_kind": "daily-summary",
                "last_status": "accepted",
                "last_trigger": "scheduler-daily-summary",
                "message": "Resumen diario programado en segundo plano.",
                "details": {
                    "job_id": "daily-summary-123",
                    "started": True,
                },
            },
            True,
        )

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_daily_summary_report",
        fake_start_daily_summary_report,
    )

    response = client.post(
        "/api/internal/scheduler/daily-summary",
        headers={"X-Scheduler-Token": "scheduler-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["details"]["details"]["job_id"] == "daily-summary-123"


def test_internal_scheduler_possible_results_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.settings.scheduler_service_token", "scheduler-test-token")

    async def fake_start_possible_results_report():
        return (
            {
                "last_kind": "possible-results",
                "last_status": "accepted",
                "last_trigger": "scheduler-possible-results",
                "message": "Resumen de posibles resultados programado en segundo plano.",
                "details": {
                    "job_id": "possible-results-123",
                    "preview_only": False,
                    "started": True,
                },
            },
            True,
        )

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_possible_results_report",
        fake_start_possible_results_report,
    )

    response = client.post(
        "/api/internal/scheduler/possible-results",
        headers={"X-Scheduler-Token": "scheduler-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["details"]["details"]["job_id"] == "possible-results-123"


def test_internal_scheduler_weekly_backfill_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.settings.scheduler_service_token", "scheduler-test-token")

    async def fake_start_weekly_recovery_backfill():
        return (
            {
                "last_kind": "weekly-backfill",
                "last_status": "accepted",
                "last_trigger": "scheduler-weekly",
                "message": "Backfill semanal programado en segundo plano.",
                "details": {
                    "job_id": "weekly-backfill-123",
                    "days": 7,
                    "started": True,
                },
            },
            True,
        )

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_weekly_recovery_backfill",
        fake_start_weekly_recovery_backfill,
    )

    response = client.post(
        "/api/internal/scheduler/weekly-backfill",
        headers={"X-Scheduler-Token": "scheduler-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["details"]["details"]["job_id"] == "weekly-backfill-123"


def test_default_backtesting_endpoint_returns_placeholder_when_snapshot_is_missing(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.monitoring.db_service.get_latest_analytics_snapshot", lambda snapshot_prefix=None: None)
    triggered = {"called": False}

    def fake_start_backtesting_snapshot_refresh():
        triggered["called"] = True
        return True

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.start_backtesting_snapshot_refresh",
        fake_start_backtesting_snapshot_refresh,
    )

    response = client.get("/api/analytics/backtesting", headers=admin_headers, params={"days": 30})

    assert response.status_code == 200
    assert response.json()["calibration_summary"].startswith("El snapshot de backtesting")
    assert triggered["called"] is True


def test_export_routes_return_downloadable_files(client, admin_headers):
    today = local_now().date()
    db_service.upsert_results(
        [
            make_result(today, "08:00", 12, "Lotto Activo"),
            make_result(today, "09:00", 21, "La Granjita"),
        ]
    )

    csv_response = client.get(
        "/api/admin/export/history.csv",
        headers=admin_headers,
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
    )
    pdf_response = client.get("/api/admin/export/possible-results.pdf", headers=admin_headers)

    assert csv_response.status_code == 200
    assert "attachment; filename=\"animalitos-history.csv\"" in csv_response.headers["content-disposition"]
    assert "draw_date" in csv_response.text
    assert pdf_response.status_code == 200
    assert "attachment; filename=\"animalitos-possible-results.pdf\"" in pdf_response.headers["content-disposition"]
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert len(pdf_response.content) > 100


def test_enjaulados_strategies_and_today_review_routes(client, admin_headers, monkeypatch):
    generated_at = datetime(2026, 3, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_enjaulados_summary",
        lambda force_refresh=False: {
            "generated_at": generated_at,
            "lotteries": [
                {
                    "canonical_lottery_name": "Lotto Activo",
                    "source_url": "https://example.com/enjaulados",
                    "generated_at": generated_at,
                    "items": [
                        {
                            "animal_number": 17,
                            "animal_name": "Pavo",
                            "last_seen_date": "2026-03-09",
                            "days_without_hit": 11,
                        }
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_strategies_summary",
        lambda force_refresh=False: {
            "generated_at": generated_at,
            "draw_date": "2026-03-20",
            "methodology_version": "ops-intraday-ranking-v6",
            "sources": [
                {
                    "key": "la-bola-de-cristal",
                    "title": "La Bola de Cristal",
                    "source_url": "https://example.com/bola",
                    "generated_at": generated_at,
                    "animals": [{"animal_number": 6, "animal_name": "Rana"}],
                }
            ],
            "performance": [
                {
                    "key": "la-bola-de-cristal",
                    "title": "La Bola de Cristal",
                    "hit_count_today": 2,
                    "evaluated_results_today": 10,
                    "hit_rate_today": 0.2,
                    "matching_animals_today": [{"animal_number": 6, "animal_name": "Rana"}],
                    "overlap_with_system_top5": ["Lotto Activo: 06"],
                }
            ],
            "consensus": [
                {
                    "animal_number": 6,
                    "animal_name": "Rana",
                    "mention_count": 2,
                    "sources": ["La Bola de Cristal", "La Formula Ganadora"],
                    "overlap_with_system_top5": ["Lotto Activo"],
                    "hits_today": 1,
                }
            ],
            "notes": ["Senales externas solo para comparacion."],
        },
    )
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_today_prediction_review",
        lambda draw_date=None: {
            "generated_at": generated_at,
            "draw_date": "2026-03-20",
            "methodology_version": "ops-intraday-ranking-v6",
            "evaluated_draws": 3,
            "hit_top_1": 1,
            "hit_top_3": 1,
            "hit_top_5": 2,
            "hit_top_1_rate": 0.3333,
            "hit_top_3_rate": 0.3333,
            "hit_top_5_rate": 0.6667,
            "by_lottery": [
                {
                    "canonical_lottery_name": "Lotto Activo",
                    "evaluated_draws": 1,
                    "hit_top_1": 0,
                    "hit_top_3": 0,
                    "hit_top_5": 1,
                    "hit_top_1_rate": 0,
                    "hit_top_3_rate": 0,
                    "hit_top_5_rate": 1,
                }
            ],
            "windows": [],
            "notes": ["Top 5 acerto 2 de 3."],
        },
    )

    enjaulados_response = client.get("/api/analytics/enjaulados", headers=admin_headers)
    strategies_response = client.get("/api/analytics/strategies", headers=admin_headers)
    review_response = client.get("/api/analytics/today-review", headers=admin_headers)

    assert enjaulados_response.status_code == 200
    assert strategies_response.status_code == 200
    assert review_response.status_code == 200
    assert enjaulados_response.json()["lotteries"][0]["items"][0]["animal_number"] == 17
    assert strategies_response.json()["sources"][0]["title"] == "La Bola de Cristal"
    assert review_response.json()["hit_top_5"] == 2


def test_today_review_route_prefers_cached_snapshot(client, admin_headers, monkeypatch):
    generated_at = datetime(2026, 3, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.api.monitoring.local_now",
        lambda: datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "app.api.monitoring.db_service.get_analytics_snapshot",
        lambda snapshot_key: {
            "generated_at": generated_at,
            "draw_date": "2026-03-23",
            "methodology_version": "ops-hybrid-ranking-v10",
            "evaluated_draws": 10,
            "hit_top_1": 1,
            "hit_top_3": 2,
            "hit_top_5": 4,
            "hit_top_1_rate": 0.1,
            "hit_top_3_rate": 0.2,
            "hit_top_5_rate": 0.4,
            "by_lottery": [],
            "by_hour": [],
            "by_signal": [],
            "windows": [],
            "notes": ["snapshot"],
        }
        if snapshot_key.startswith("today-review:")
        else None,
    )
    monkeypatch.setattr("app.api.monitoring.db_service.get_latest_analytics_snapshot", lambda snapshot_prefix: None)
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_today_prediction_review",
        lambda draw_date=None: (_ for _ in ()).throw(AssertionError("snapshot should avoid rebuild")),
    )

    response = client.get("/api/analytics/today-review", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["evaluated_draws"] == 10


def test_today_analysis_route_rebuilds_when_snapshot_is_stale(client, admin_headers, monkeypatch):
    stale_generated_at = datetime(2026, 3, 24, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.api.monitoring.local_now",
        lambda: datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        "app.api.monitoring.db_service.get_analytics_snapshot",
        lambda snapshot_key: {
            "generated_at": stale_generated_at,
            "draw_date": "2026-03-24",
            "day_regime": "volatil",
            "operating_mode": "conservative",
            "observed_results": [],
            "system_hits_top1_top3_top5_so_far": {
                "evaluated_draws": 0,
                "hit_top_1": 0,
                "hit_top_3": 0,
                "hit_top_5": 0,
                "hit_top_1_rate": 0,
                "hit_top_3_rate": 0,
                "hit_top_5_rate": 0,
            },
            "strategy_performance_today": [],
            "forecast_by_lottery": [],
            "notes": ["stale"],
        }
        if snapshot_key.startswith("today-analysis:")
        else None,
    )
    monkeypatch.setattr("app.api.monitoring.db_service.get_latest_analytics_snapshot", lambda snapshot_prefix: None)

    async def fresh_today_analysis(force_refresh=False):
        return {
            "generated_at": datetime(2026, 3, 26, tzinfo=timezone.utc),
            "draw_date": "2026-03-26",
            "day_regime": "estable",
            "operating_mode": "balanced",
            "observed_results": [],
            "system_hits_top1_top3_top5_so_far": {
                "evaluated_draws": 0,
                "hit_top_1": 0,
                "hit_top_3": 0,
                "hit_top_5": 0,
                "hit_top_1_rate": 0,
                "hit_top_3_rate": 0,
                "hit_top_5_rate": 0,
            },
            "strategy_performance_today": [],
            "forecast_by_lottery": [],
            "notes": ["fresh"],
        }

    monkeypatch.setattr("app.api.monitoring.monitoring_service.build_today_analysis", fresh_today_analysis)

    response = client.get("/api/analytics/today-analysis", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["draw_date"] == "2026-03-26"


def test_possible_results_route_rebuilds_when_snapshot_is_stale(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.monitoring.local_now",
        lambda: datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "app.api.monitoring.db_service.get_analytics_snapshot",
        lambda snapshot_key: {
            "generated_at": datetime(2026, 3, 24, tzinfo=timezone.utc),
            "reference_date": "2026-03-24",
            "reference_time_local": "08:00",
            "methodology_version": "ops-hybrid-ranking-v10",
            "ensemble_version": "hybrid-ensemble-v3",
            "baseline_methodology_version": "frequency-baseline-v1",
            "methodology": "stale",
            "disclaimer": "stale",
            "history_days_covered": 30,
            "history_results_considered": 1000,
            "model_version_by_segment": {},
            "score_components": [],
            "lotteries": [],
            "change_alerts": [],
            "prediction_stability": {},
            "operating_mode": "conservative",
            "operating_notes": ["stale"],
        }
        if snapshot_key.startswith("possible-results:default:")
        else None,
    )
    monkeypatch.setattr("app.api.monitoring.db_service.get_latest_analytics_snapshot", lambda snapshot_prefix: None)
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_possible_results_summary",
        lambda **_kwargs: {
            "generated_at": datetime(2026, 3, 26, tzinfo=timezone.utc),
            "reference_date": "2026-03-26",
            "reference_time_local": "08:00",
            "methodology_version": "ops-hybrid-ranking-v10",
            "ensemble_version": "hybrid-ensemble-v3",
            "baseline_methodology_version": "frequency-baseline-v1",
            "methodology": "fresh",
            "disclaimer": "fresh",
            "history_days_covered": 30,
            "history_results_considered": 1000,
            "model_version_by_segment": {},
            "score_components": [],
            "lotteries": [],
            "change_alerts": [],
            "prediction_stability": {},
            "operating_mode": "balanced",
            "operating_notes": ["fresh"],
        },
    )

    response = client.get("/api/analytics/possible-results", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["reference_date"] == "2026-03-26"


def test_today_review_route_prefers_exact_historical_snapshot(client, admin_headers, monkeypatch):
    generated_at = datetime(2026, 3, 23, tzinfo=timezone.utc)

    def fake_snapshot(snapshot_key):
        if snapshot_key == "today-review:2026-03-23":
            return {
                "generated_at": generated_at,
                "draw_date": "2026-03-23",
                "methodology_version": "ops-hybrid-ranking-v10",
                "evaluated_draws": 49,
                "hit_top_1": 2,
                "hit_top_3": 5,
                "hit_top_5": 7,
                "hit_top_1_rate": 0.0408,
                "hit_top_3_rate": 0.102,
                "hit_top_5_rate": 0.1429,
                "by_lottery": [],
                "by_hour": [],
                "by_signal": [],
                "windows": [],
                "notes": ["historical snapshot"],
            }
        return None

    monkeypatch.setattr("app.api.monitoring.db_service.get_analytics_snapshot", fake_snapshot)
    monkeypatch.setattr(
        "app.api.monitoring.analytics_service.build_today_prediction_review",
        lambda draw_date=None: (_ for _ in ()).throw(AssertionError("historical snapshot should avoid rebuild")),
    )

    response = client.get("/api/analytics/today-review?draw_date=2026-03-23", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["evaluated_draws"] == 49


def test_today_analysis_route_returns_operational_snapshot(client, admin_headers, monkeypatch):
    generated_at = datetime(2026, 3, 22, tzinfo=timezone.utc)

    async def fake_build_today_analysis(force_refresh=False):
        return {
            "generated_at": generated_at,
            "draw_date": "2026-03-22",
            "day_regime": "volatil",
            "observed_results": [
                {
                    "canonical_lottery_name": "Lotto Activo",
                    "draw_time_local": "08:00",
                    "animal_number": 24,
                    "animal_name": "Iguana",
                    "source_url": "https://example.com",
                    "source_page": "animalitos",
                }
            ],
            "system_hits_top1_top3_top5_so_far": {
                "evaluated_draws": 2,
                "hit_top_1": 0,
                "hit_top_3": 1,
                "hit_top_5": 1,
                "hit_top_1_rate": 0,
                "hit_top_3_rate": 0.5,
                "hit_top_5_rate": 0.5,
            },
            "strategy_performance_today": [
                {
                    "key": "el-mago-de-los-numeros",
                    "title": "El Mago de los Numeros",
                    "hit_count_today": 2,
                    "evaluated_results_today": 6,
                    "hit_rate_today": 0.3333,
                    "matching_animals_today": [{"animal_number": 1, "animal_name": "Carnero"}],
                    "overlap_with_system_top5": ["Lotto Activo: 01, 17"],
                }
            ],
            "forecast_by_lottery": [
                {
                    "canonical_lottery_name": "Lotto Activo",
                    "next_draw_time_local": "10:00",
                    "remaining_draws_today": 10,
                    "candidates": [
                        {
                            "animal_number": 17,
                            "animal_name": "Pavo",
                            "score": 0.81,
                            "signal_leader": "enjaulado_pressure",
                            "confidence_band": "alta",
                            "enjaulado_days_without_hit": 13,
                            "strategy_mentions": 2,
                            "strategy_hit_rate": 0.66,
                            "rationale": "Lidera por enjaulado pressure",
                        }
                    ],
                }
            ],
            "notes": ["La jornada sigue volatil."],
        }

    monkeypatch.setattr(
        "app.api.monitoring.monitoring_service.build_today_analysis",
        fake_build_today_analysis,
    )
    monkeypatch.setattr("app.api.monitoring.db_service.get_analytics_snapshot", lambda snapshot_key: None)
    monkeypatch.setattr("app.api.monitoring.db_service.get_latest_analytics_snapshot", lambda snapshot_prefix=None: None)

    response = client.get("/api/analytics/today-analysis", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["day_regime"] == "volatil"
    assert response.json()["observed_results"][0]["animal_number"] == 24
    assert response.json()["forecast_by_lottery"][0]["candidates"][0]["animal_number"] == 17


def test_admin_user_management_and_password_rotation(client, admin_headers):
    create_response = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "operador1",
            "temporary_password": "Temporal123",
            "role": "user",
        },
    )
    list_response = client.get("/api/admin/users", headers=admin_headers)
    login_response = client.post(
        "/api/auth/login",
        json={"username": "operador1", "password": "Temporal123"},
    )
    change_response = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
        json={"current_password": "Temporal123", "new_password": "ClaveNueva123"},
    )
    reset_response = client.post(
        "/api/admin/users/operador1/reset-password",
        headers=admin_headers,
        json={"temporary_password": "Temporal456"},
    )
    second_login_response = client.post(
        "/api/auth/login",
        json={"username": "operador1", "password": "Temporal456"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["must_change_password"] is True
    assert list_response.status_code == 200
    assert any(item["username"] == "operador1" for item in list_response.json())
    assert login_response.status_code == 200
    assert login_response.json()["user"]["must_change_password"] is True
    assert change_response.status_code == 200
    assert change_response.json()["must_change_password"] is False
    assert reset_response.status_code == 200
    assert second_login_response.status_code == 200
    assert second_login_response.json()["user"]["must_change_password"] is True
