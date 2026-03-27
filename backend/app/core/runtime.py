from copy import deepcopy

from fastapi import HTTPException, status

from app.core.config import settings


_startup_issues: list[dict[str, str]] = []


def reset_startup_issues() -> None:
    _startup_issues.clear()


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


def database_required() -> bool:
    return settings.database_provider.lower() in {"postgres", "supabase"}


def database_operational() -> bool:
    if not database_required():
        return True

    from app.services.database import db_service

    return db_service.is_postgres_mode


def runtime_status_snapshot() -> dict:
    database_connected = database_operational()
    return {
        "database_required": database_required(),
        "database_connected": database_connected,
        "degraded": bool(database_required() and not database_connected),
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
