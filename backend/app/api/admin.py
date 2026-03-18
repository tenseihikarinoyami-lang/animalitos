import csv
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.api.auth import require_admin
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.schemas import (
    AdminResetPasswordRequest,
    AdminActionResponse,
    AdminUserCreateRequest,
    AuditLogEntry,
    BackfillRequest,
    PredictionRunRequest,
    QualityReportResponse,
    RefreshResponse,
    SystemStatusResponse,
    UserResponse,
)
from app.services.schedule import utc_now
from app.services.analytics import analytics_service
from app.services.database import db_service
from app.services.monitoring import monitoring_service
from app.services.rate_limit import limit_admin_requests
from app.services.telegram import telegram_service


router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(limit_admin_requests)])


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _audit_admin_action(
    *,
    action: str,
    current_user: dict,
    request: Request,
    status_value: str,
    details: dict,
) -> None:
    db_service.save_audit_log(
        {
            "action": action,
            "actor_username": current_user.get("username", "unknown"),
            "actor_role": current_user.get("role", "unknown"),
            "status": status_value,
            "source_ip": _client_host(request),
            "details": details,
        }
    )


def _parse_lotteries(raw_value: str | None) -> list[str] | None:
    if not raw_value:
        return None
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _build_possible_results_csv(summary: dict) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "generated_at",
            "lottery_name",
            "next_draw_time_local",
            "animal_number",
            "animal_name",
            "score",
            "overall_hits",
            "recent_hits",
            "remaining_time_hits",
            "draws_since_last_seen",
            "seen_today",
        ]
    )
    for lottery in summary.get("lotteries", []):
        for candidate in lottery.get("candidates", []):
            writer.writerow(
                [
                    summary.get("generated_at"),
                    lottery.get("canonical_lottery_name"),
                    lottery.get("next_draw_time_local"),
                    candidate.get("animal_number"),
                    candidate.get("animal_name"),
                    candidate.get("score"),
                    candidate.get("overall_hits"),
                    candidate.get("recent_hits"),
                    candidate.get("remaining_time_hits"),
                    candidate.get("draws_since_last_seen"),
                    candidate.get("seen_today"),
                ]
            )
    return buffer.getvalue()


def _build_history_csv(items: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "draw_date",
            "draw_time_local",
            "canonical_lottery_name",
            "animal_number",
            "animal_name",
            "source_url",
            "status",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item.get("draw_date"),
                item.get("draw_time_local"),
                item.get("canonical_lottery_name"),
                item.get("animal_number"),
                item.get("animal_name"),
                item.get("source_url"),
                item.get("status"),
            ]
        )
    return buffer.getvalue()


def _build_possible_results_pdf(summary: dict) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "Animalitos Monitor - Tendencia Estadistica")
    y -= 22
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Metodo: {summary.get('methodology_version')} | Generado: {summary.get('generated_at')}")
    y -= 20

    for lottery in summary.get("lotteries", []):
        if y < 120:
            pdf.showPage()
            y = height - 50
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(40, y, lottery.get("canonical_lottery_name", ""))
        y -= 16
        pdf.setFont("Helvetica", 10)
        pdf.drawString(
            40,
            y,
            f"Proximo: {lottery.get('next_draw_time_local') or 'Sin sorteo pendiente'} | Pendientes: {lottery.get('remaining_draws_today', 0)}",
        )
        y -= 16
        for candidate in lottery.get("candidates", [])[:10]:
            if y < 80:
                pdf.showPage()
                y = height - 50
            line = (
                f"{candidate.get('animal_number', 0):02d} {candidate.get('animal_name', '')} | "
                f"score {candidate.get('score', 0)} | hist {candidate.get('overall_hits', 0)} | "
                f"rec {candidate.get('recent_hits', 0)}"
            )
            pdf.drawString(55, y, line[:110])
            y -= 14
        y -= 10

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(40, 35, "Reporte estadistico de apoyo operativo. No garantiza aciertos.")
    pdf.save()
    return buffer.getvalue()


def _resolve_summary_for_export(top_n: int | None, lotteries: list[str] | None) -> dict:
    latest_prediction = db_service.get_latest_prediction_run()
    if latest_prediction and not top_n and not lotteries:
        return latest_prediction.get("summary", {})
    return analytics_service.build_possible_results_summary(top_n=top_n, lotteries=lotteries).model_dump()


@router.post("/results/refresh", response_model=RefreshResponse)
async def refresh_results(request: Request, current_user: dict = Depends(require_admin)):
    response = await monitoring_service.refresh_today(trigger="manual", notify=True)
    _audit_admin_action(
        action="results_refresh",
        current_user=current_user,
        request=request,
        status_value=response["ingestion_run"]["status"],
        details={"new_results": response["ingestion_run"]["new_results"]},
    )
    return response


@router.post("/backfill", response_model=AdminActionResponse)
async def backfill_results(
    request: Request,
    payload: BackfillRequest,
    current_user: dict = Depends(require_admin),
):
    response = await monitoring_service.backfill(request=payload, trigger="manual")
    _audit_admin_action(
        action="results_backfill",
        current_user=current_user,
        request=request,
        status_value="success",
        details=response["details"],
    )
    return response


@router.post("/telegram/test", response_model=AdminActionResponse)
async def test_telegram(request: Request, current_user: dict = Depends(require_admin)):
    result = await telegram_service.test_connection()
    _audit_admin_action(
        action="telegram_test",
        current_user=current_user,
        request=request,
        status_value="success" if result.get("success") else "failed",
        details=result,
    )
    return {
        "message": "Telegram test completed",
        "details": result,
    }


@router.post("/telegram/possible-results", response_model=AdminActionResponse)
async def send_possible_results_to_telegram(
    request: Request,
    payload: PredictionRunRequest | None = None,
    current_user: dict = Depends(require_admin),
):
    payload = payload or PredictionRunRequest()
    response = await monitoring_service.send_today_possible_results(
        top_n=payload.top_n,
        lotteries=payload.lotteries,
        preview_only=payload.preview_only,
    )
    _audit_admin_action(
        action="possible_results_send",
        current_user=current_user,
        request=request,
        status_value="success" if response["details"]["sent"] or payload.preview_only else "failed",
        details={
            "prediction_run_id": response["details"]["prediction_run_id"],
            "preview_only": payload.preview_only,
            "top_n": payload.top_n,
            "lotteries": payload.lotteries,
        },
    )
    return response


@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(current_user: dict = Depends(require_admin)):
    from app.main import scheduler

    return analytics_service.build_system_status(scheduler_running=(scheduler.running or settings.use_external_scheduler))


@router.get("/system/quality", response_model=QualityReportResponse)
async def get_system_quality(
    days: int = Query(default=14, ge=1, le=120),
    lotteries: str | None = None,
    current_user: dict = Depends(require_admin),
):
    return analytics_service.build_quality_report(days=days, lotteries=_parse_lotteries(lotteries))


@router.get("/system/audit", response_model=list[AuditLogEntry])
async def get_system_audit(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return analytics_service.build_audit_entries(limit=limit)


@router.get("/users", response_model=list[UserResponse])
async def list_users(current_user: dict = Depends(require_admin)):
    users = []
    for user in db_service.list_users(limit=None):
        users.append(
            {
                "id": user["username"],
                "username": user["username"],
                "email": user.get("email"),
                "full_name": user.get("full_name"),
                "role": user.get("role", "user"),
                "is_active": user.get("is_active", True),
                "created_at": user.get("created_at"),
                "must_change_password": user.get("must_change_password", False),
                "password_changed_at": user.get("password_changed_at"),
            }
        )
    return users


@router.post("/users", response_model=UserResponse)
async def create_temporary_user(
    request: Request,
    payload: AdminUserCreateRequest,
    current_user: dict = Depends(require_admin),
):
    if db_service.get_user(payload.username):
        raise HTTPException(status_code=400, detail="Username already exists")

    user_payload = {
        "username": payload.username,
        "email": payload.email,
        "full_name": payload.full_name,
        "role": payload.role or "user",
        "password": get_password_hash(payload.temporary_password),
        "is_active": True,
        "must_change_password": True,
        "password_changed_at": None,
        "created_at": utc_now(),
    }
    db_service.save_user(user_payload)
    _audit_admin_action(
        action="user_create_temporary",
        current_user=current_user,
        request=request,
        status_value="success",
        details={"username": payload.username, "role": payload.role or "user"},
    )
    created = db_service.get_user(payload.username)
    return {
        "id": created["username"],
        "username": created["username"],
        "email": created.get("email"),
        "full_name": created.get("full_name"),
        "role": created.get("role", "user"),
        "is_active": created.get("is_active", True),
        "created_at": created.get("created_at"),
        "must_change_password": created.get("must_change_password", False),
        "password_changed_at": created.get("password_changed_at"),
    }


@router.post("/users/{username}/reset-password", response_model=AdminActionResponse)
async def reset_user_password(
    username: str,
    payload: AdminResetPasswordRequest,
    request: Request,
    current_user: dict = Depends(require_admin),
):
    existing = db_service.get_user(username)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    db_service.update_user(
        username,
        {
            "password": get_password_hash(payload.temporary_password),
            "must_change_password": True,
            "password_changed_at": None,
        },
    )
    _audit_admin_action(
        action="user_reset_password",
        current_user=current_user,
        request=request,
        status_value="success",
        details={"username": username},
    )
    return {
        "message": "Temporary password updated successfully",
        "details": {"username": username, "must_change_password": True},
    }


@router.get("/export/history.csv")
async def export_history_csv(
    request: Request,
    lottery_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    draw_time_local: str | None = None,
    current_user: dict = Depends(require_admin),
):
    items = db_service.get_results(
        canonical_lottery_name=lottery_name,
        start_date=start_date,
        end_date=end_date,
        draw_time_local=draw_time_local,
        limit=None,
    )
    _audit_admin_action(
        action="export_history_csv",
        current_user=current_user,
        request=request,
        status_value="success",
        details={"rows": len(items)},
    )
    data = _build_history_csv(items)
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="animalitos-history.csv"'},
    )


@router.get("/export/possible-results.csv")
async def export_possible_results_csv(
    request: Request,
    top_n: int | None = None,
    lotteries: str | None = None,
    current_user: dict = Depends(require_admin),
):
    summary = _resolve_summary_for_export(top_n=top_n, lotteries=_parse_lotteries(lotteries))
    _audit_admin_action(
        action="export_possible_results_csv",
        current_user=current_user,
        request=request,
        status_value="success",
        details={"lotteries": len(summary.get("lotteries", []))},
    )
    data = _build_possible_results_csv(summary)
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="animalitos-possible-results.csv"'},
    )


@router.get("/export/possible-results.pdf")
async def export_possible_results_pdf(
    request: Request,
    top_n: int | None = None,
    lotteries: str | None = None,
    current_user: dict = Depends(require_admin),
):
    summary = _resolve_summary_for_export(top_n=top_n, lotteries=_parse_lotteries(lotteries))
    _audit_admin_action(
        action="export_possible_results_pdf",
        current_user=current_user,
        request=request,
        status_value="success",
        details={"lotteries": len(summary.get("lotteries", []))},
    )
    pdf_bytes = _build_possible_results_pdf(summary)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="animalitos-possible-results.pdf"'},
    )
