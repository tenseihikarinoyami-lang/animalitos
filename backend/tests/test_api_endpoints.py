from datetime import date, datetime, timedelta, timezone

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
    assert audit_response.json()[0]["action"] == "results_refresh"
    assert "overall_top_3_rate" in backtesting_response.json()


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
