from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, get_password_hash, verify_password
from app.models.schemas import PasswordChangeRequest, Token, UserCreate, UserLogin, UserResponse
from app.services.database import db_service
from app.services.rate_limit import limit_auth_requests
from app.services.schedule import utc_now


router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _save_audit_log(
    *,
    action: str,
    actor_username: str,
    actor_role: str,
    status_value: str,
    source_ip: str,
    details: dict,
) -> None:
    db_service.save_audit_log(
        {
            "action": action,
            "actor_username": actor_username,
            "actor_role": actor_role,
            "status": status_value,
            "source_ip": source_ip,
            "details": details,
        }
    )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db_service.get_user(username)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, request: Request, _: None = Depends(limit_auth_requests)):
    if db_service.get_user(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    payload = user_data.model_dump()
    payload["password"] = get_password_hash(user_data.password)
    payload["role"] = "user"
    payload["is_active"] = True
    user_id = db_service.save_user(payload)

    return {
        "id": user_id,
        "username": user_data.username,
        "email": user_data.email,
        "full_name": user_data.full_name,
        "role": payload["role"],
        "is_active": True,
        "created_at": db_service.get_user(user_data.username).get("created_at"),
        "must_change_password": False,
        "password_changed_at": db_service.get_user(user_data.username).get("password_changed_at"),
    }


@router.post("/login", response_model=Token)
async def login(login_data: UserLogin, request: Request, _: None = Depends(limit_auth_requests)):
    user = db_service.get_user(login_data.username)
    if not user or not verify_password(login_data.password, user.get("password", "")):
        if user and user.get("role") == "admin":
            _save_audit_log(
                action="admin_login",
                actor_username=login_data.username,
                actor_role="admin",
                status_value="failed",
                source_ip=_client_host(request),
                details={"reason": "invalid_credentials"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    if user.get("role") == "admin":
        _save_audit_log(
            action="admin_login",
            actor_username=user["username"],
            actor_role="admin",
            status_value="success",
            source_ip=_client_host(request),
            details={"message": "Admin session created"},
        )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["username"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "role": user.get("role", "user"),
            "is_active": user.get("is_active", True),
            "created_at": user.get("created_at"),
            "must_change_password": user.get("must_change_password", False),
            "password_changed_at": user.get("password_changed_at"),
        },
    }


@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["username"],
        "username": current_user["username"],
        "email": current_user["email"],
        "full_name": current_user.get("full_name"),
        "role": current_user.get("role", "user"),
        "is_active": current_user.get("is_active", True),
        "created_at": current_user.get("created_at"),
        "must_change_password": current_user.get("must_change_password", False),
        "password_changed_at": current_user.get("password_changed_at"),
    }


@router.post("/change-password", response_model=UserResponse)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(limit_auth_requests),
):
    if not verify_password(payload.current_password, current_user.get("password", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    updated_user = db_service.update_user(
        current_user["username"],
        {
            "password": get_password_hash(payload.new_password),
            "must_change_password": False,
            "password_changed_at": utc_now(),
        },
    )
    _save_audit_log(
        action="change_password",
        actor_username=current_user["username"],
        actor_role=current_user.get("role", "user"),
        status_value="success",
        source_ip=_client_host(request),
        details={"must_change_password_cleared": True},
    )
    refreshed = db_service.get_user(current_user["username"])
    return {
        "id": refreshed["username"],
        "username": refreshed["username"],
        "email": refreshed.get("email"),
        "full_name": refreshed.get("full_name"),
        "role": refreshed.get("role", "user"),
        "is_active": refreshed.get("is_active", True),
        "created_at": refreshed.get("created_at"),
        "must_change_password": refreshed.get("must_change_password", False),
        "password_changed_at": refreshed.get("password_changed_at"),
    }


@router.post("/bootstrap-admin")
async def bootstrap_admin_user(
    user_data: UserCreate,
    request: Request,
    bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
    _: None = Depends(limit_auth_requests),
):
    existing_admin = next(
        (user for user in [db_service.get_user(settings.bootstrap_admin_username)] if user),
        None,
    )
    if not existing_admin:
        existing_admin = next(
            (
                item
                for item in [db_service.get_user(user_data.username)]
                if item and item.get("role") == "admin"
            ),
            None,
        )
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An admin user already exists",
        )

    if not settings.bootstrap_admin_token or bootstrap_token != settings.bootstrap_admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bootstrap token",
        )

    if db_service.get_user(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    payload = user_data.model_dump()
    payload["password"] = get_password_hash(user_data.password)
    payload["role"] = "admin"
    payload["is_active"] = True
    db_service.save_user(payload)
    _save_audit_log(
        action="bootstrap_admin",
        actor_username=user_data.username,
        actor_role="admin",
        status_value="success",
        source_ip=_client_host(request),
        details={"message": "Admin bootstrapped through protected endpoint"},
    )
    return {
        "message": "Admin user bootstrapped successfully",
        "username": user_data.username,
    }


@router.post("/create-admin")
async def create_admin_user(current_user: dict = Depends(require_admin)):
    existing = db_service.get_user("admin")
    if existing:
        return {"message": "Admin user already exists"}

    payload = {
        "username": "admin",
        "email": settings.bootstrap_admin_email,
        "password": get_password_hash(settings.bootstrap_admin_password or "change-me-now"),
        "full_name": settings.bootstrap_admin_full_name,
        "role": "admin",
        "is_active": True,
    }
    db_service.save_user(payload)
    return {
        "message": "Admin user created successfully",
        "credentials": {"username": "admin"},
    }
