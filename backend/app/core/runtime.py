from copy import deepcopy

from fastapi import HTTPException, status

from app.core.config import settings


_startup_issues: list[dict[str, str]] = []
_startup_phase = "starting"
_database_connected: bool | None = None


def reset_startup_issues() -> None:
    _startup_issues.clear()
    global _startup_phase, _database_connected
    _startup_phase = "starting"
    _database_connected = None


def register_startup_issue(component: str, message: str, error: Exception | str | None = None) -> dict[str, str]:
    issue = {
        "component": component,
        "message": message,
    }
    if error:
        issue["error"] = str(error)
    _startup_issues.append(issue)
    return issue


def get_startup_issues() -> list[dict[str, str]]:
    return deepcopy(_startup_issues)


def mark_startup_phase(phase: str) -> None:
    global _startup_phase
    _startup_phase = phase


def mark_database_status(connected: bool | None) -> None:
    global _database_connected
    _database_connected = connected


def database_required() -> bool:
    return settings.database_provider.lower() in {"postgres", "supabase"}


def refresh_database_status() -> bool:
    if not database_required():
        mark_database_status(True)
        return True

    from app.services.database import db_service

    connected = db_service.is_postgres_mode
    mark_database_status(connected)
    return connected


def database_operational() -> bool:
    if not database_required():
        return True

    if _database_connected is True:
        return True

    return refresh_database_status()


def runtime_status_snapshot() -> dict:
    database_connected = True if not database_required() else _database_connected
    degraded = bool(database_required() and database_connected is False)
    starting = _startup_phase == "starting"
    return {
        "startup_phase": _startup_phase,
        "starting": starting,
        "database_required": database_required(),
        "database_connected": database_connected,
        "degraded": degraded,
        "startup_issues": get_startup_issues(),
    }


def require_operational_database() -> None:
    if database_operational():
        return

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "El backend esta temporalmente degradado porque la base de datos no esta disponible. "
            "Intenta de nuevo en unos minutos."
        ),
    )
