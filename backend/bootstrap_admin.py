from app.core.config import settings
from app.core.security import get_password_hash
from app.services.database import db_service


def main() -> None:
    if not settings.bootstrap_admin_password:
        print("BOOTSTRAP_ADMIN_PASSWORD is empty. Nothing to bootstrap.")
        return

    existing = db_service.get_user(settings.bootstrap_admin_username)
    if existing:
        payload = {
            "username": settings.bootstrap_admin_username,
            "email": settings.bootstrap_admin_email or existing.get("email"),
            "password": existing.get("password"),
            "full_name": settings.bootstrap_admin_full_name or existing.get("full_name"),
            "role": "admin",
            "is_active": True,
            "created_at": existing.get("created_at"),
            "must_change_password": existing.get("must_change_password", False),
            "password_changed_at": existing.get("password_changed_at"),
        }
        db_service.save_user(payload)
        print(f"Admin bootstrap preserved existing password for user: {settings.bootstrap_admin_username}")
        return

    payload = {
        "username": settings.bootstrap_admin_username,
        "email": settings.bootstrap_admin_email,
        "password": get_password_hash(settings.bootstrap_admin_password),
        "full_name": settings.bootstrap_admin_full_name,
        "role": "admin",
        "is_active": True,
    }
    db_service.save_user(payload)
    print(f"Admin bootstrap synchronized for user: {settings.bootstrap_admin_username}")


if __name__ == "__main__":
    main()
