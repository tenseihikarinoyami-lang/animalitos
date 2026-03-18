from app.core.config import settings
from app.core.postgres import initialize_postgres
from app.core.security import get_password_hash
from app.services.database import db_service


def main() -> None:
    if not settings.use_postgres or not settings.database_url:
        print("DATABASE_URL is empty or DATABASE_PROVIDER is not configured for postgres.")
        return

    if not initialize_postgres():
        raise SystemExit("Postgres schema initialization failed.")

    db_service.ensure_default_schedules()

    if settings.bootstrap_admin_password:
        db_service.save_user(
            {
                "username": settings.bootstrap_admin_username,
                "email": settings.bootstrap_admin_email,
                "password": get_password_hash(settings.bootstrap_admin_password),
                "full_name": settings.bootstrap_admin_full_name,
                "role": "admin",
                "is_active": True,
            }
        )

    print("Postgres/Supabase schema initialized successfully.")


if __name__ == "__main__":
    main()
