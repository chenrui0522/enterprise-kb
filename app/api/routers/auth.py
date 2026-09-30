from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import write_audit
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import AppError
from app.core.redis import get_redis
from app.identity.constants import (
    PERM_USERS_MANAGE,
    SESSION_COOKIE_NAME,
)
from app.identity.deps import get_current_principal, require_permission
from app.identity.feature_gates import can_use_leave_ledger, can_use_staffing
from app.identity.loader import load_principal
from app.identity.passwords import hash_password, verify_password
from app.identity.principal import Principal
from app.identity.sessions import create_session, revoke_session, revoke_user_sessions
from app.models.identity import User
from app.schemas.identity import (
    BindPositionRequest,
    ClearanceUpdate,
    EstablishmentRequest,
    LoginRequest,
    PrincipalOut,
    UserCreate,
    validate_clearance,
    validate_site,
)
from app.models.identity import Position, UserOrgRelation, UserPosition
from app.identity.constants import RELATION_ESTABLISHMENT

router = APIRouter(tags=["auth"])


def _principal_out(p: Principal) -> PrincipalOut:
    return PrincipalOut(
        user_id=p.user_id,
        tenant_id=p.tenant_id,
        username=p.username,
        display_name=p.display_name,
        site=p.site,
        clearance=p.clearance,
        org_unit_ids=list(p.org_unit_ids),
        domains=list(p.domains),
        project_ids=list(p.project_ids),
        permissions=list(p.permissions),
        position_ids=list(p.position_ids),
        establishment_org_unit_ids=list(p.establishment_org_unit_ids),
        can_staffing=can_use_staffing(p, write=None),
        can_leave_ledger=can_use_leave_ledger(p, write=None),
    )


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


async def _login_locked(username: str) -> bool:
    settings = get_settings()
    redis = get_redis()
    key = f"kb:login:lock:{username}"
    try:
        return bool(await redis.exists(key))
    except Exception:
        return False


async def _record_login_failure(username: str) -> None:
    settings = get_settings()
    redis = get_redis()
    fail_key = f"kb:login:fail:{username}"
    lock_key = f"kb:login:lock:{username}"
    try:
        count = await redis.incr(fail_key)
        if count == 1:
            await redis.expire(fail_key, settings.login_lockout_seconds)
        if count >= settings.login_max_failures:
            await redis.set(lock_key, "1", ex=settings.login_lockout_seconds)
    except Exception:
        return


async def _clear_login_failures(username: str) -> None:
    redis = get_redis()
    try:
        await redis.delete(f"kb:login:fail:{username}", f"kb:login:lock:{username}")
    except Exception:
        return


@router.post("/auth/login", response_model=PrincipalOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> PrincipalOut:
    settings = get_settings()
    username = body.username.strip()
    if await _login_locked(username):
        await write_audit(
            session,
            settings.default_tenant_id,
            action="auth.login_locked",
            resource_type="user",
            resource_id=username,
            actor=username,
        )
        raise AppError("账号已锁定，请稍后再试", status_code=429)

    result = await session.execute(
        select(User).where(
            User.tenant_id == settings.default_tenant_id,
            User.username == username,
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        await _record_login_failure(username)
        await write_audit(
            session,
            settings.default_tenant_id,
            action="auth.login_failed",
            resource_type="user",
            resource_id=username,
            actor=username,
        )
        await session.commit()
        raise AppError("用户名或密码错误", status_code=401)

    await _clear_login_failures(username)
    _, token = await create_session(
        session,
        user_id=user.id,
        ttl_hours=settings.session_ttl_hours,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    principal = await load_principal(session, user.id)
    assert principal is not None
    await write_audit(
        session,
        principal.tenant_id,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        actor=user.username,
    )
    await session.commit()
    _set_session_cookie(response, token)
    return _principal_out(principal)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(get_current_principal),
) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await revoke_session(session, token)
    await write_audit(
        session,
        principal.tenant_id,
        action="auth.logout",
        resource_type="user",
        resource_id=principal.user_id,
        actor=principal.username,
    )
    await session.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=PrincipalOut)
async def me(principal: Principal = Depends(get_current_principal)) -> PrincipalOut:
    return _principal_out(principal)


@router.get("/users", response_model=list[dict])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> list[dict]:
    rows = (
        await session.execute(
            select(User)
            .where(User.tenant_id == principal.tenant_id)
            .order_by(User.username)
        )
    ).scalars().all()
    result: list[dict] = []
    for row in rows:
        position_ids = (
            await session.execute(
                select(UserPosition.position_id).where(UserPosition.user_id == row.id)
            )
        ).scalars().all()
        establishment_ids = (
            await session.execute(
                select(UserOrgRelation.org_unit_id).where(
                    UserOrgRelation.user_id == row.id,
                    UserOrgRelation.relation == RELATION_ESTABLISHMENT,
                )
            )
        ).scalars().all()
        result.append(
            {
                "id": row.id,
                "username": row.username,
                "display_name": row.display_name,
                "site": row.site,
                "clearance": row.clearance,
                "is_active": row.is_active,
                "position_ids": list(position_ids),
                "establishment_org_unit_ids": list(establishment_ids),
            }
        )
    return result


@router.post("/users", response_model=dict)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> dict:
    try:
        site = validate_site(body.site)
        clearance = validate_clearance(body.clearance)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422) from exc
    existing = await session.execute(
        select(User).where(User.tenant_id == principal.tenant_id, User.username == body.username)
    )
    if existing.scalar_one_or_none():
        raise AppError("用户名已存在", status_code=409)
    user = User(
        tenant_id=principal.tenant_id,
        username=body.username.strip(),
        display_name=body.display_name or body.username,
        password_hash=hash_password(body.password),
        site=site,
        clearance=clearance,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await write_audit(
        session,
        principal.tenant_id,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        detail={"username": user.username},
        actor=principal.username,
    )
    return {"id": user.id, "username": user.username}


@router.post("/users/{user_id}/positions", response_model=PrincipalOut)
async def bind_position(
    user_id: str,
    body: BindPositionRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> PrincipalOut:
    # Clearance is required on every post bind/change (no silent keep).
    try:
        clearance = validate_clearance(body.clearance)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422) from exc
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise AppError("用户不存在", status_code=404)
    position = await session.get(Position, body.position_id)
    if position is None or position.tenant_id != principal.tenant_id:
        raise AppError("岗位不存在", status_code=404)
    existing = await session.execute(
        select(UserPosition).where(
            UserPosition.user_id == user_id, UserPosition.position_id == body.position_id
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(UserPosition(user_id=user_id, position_id=body.position_id))
    user.clearance = clearance
    await session.flush()
    out = await load_principal(session, user_id)
    await session.commit()
    assert out is not None
    await write_audit(
        session,
        principal.tenant_id,
        action="user.bind_position",
        resource_type="user",
        resource_id=user_id,
        detail={"position_id": body.position_id, "clearance": clearance},
        actor=principal.username,
    )
    return _principal_out(out)


@router.delete("/users/{user_id}/positions/{position_id}", response_model=PrincipalOut)
async def unbind_position(
    user_id: str,
    position_id: str,
    clearance: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> PrincipalOut:
    try:
        new_clearance = validate_clearance(clearance)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422) from exc
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise AppError("用户不存在", status_code=404)
    row = (
        await session.execute(
            select(UserPosition).where(
                UserPosition.user_id == user_id, UserPosition.position_id == position_id
            )
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
    user.clearance = new_clearance
    await session.flush()
    out = await load_principal(session, user_id)
    await session.commit()
    assert out is not None
    await write_audit(
        session,
        principal.tenant_id,
        action="user.unbind_position",
        resource_type="user",
        resource_id=user_id,
        detail={"position_id": position_id, "clearance": new_clearance},
        actor=principal.username,
    )
    return _principal_out(out)


@router.patch("/users/{user_id}/clearance", response_model=PrincipalOut)
async def update_clearance(
    user_id: str,
    body: ClearanceUpdate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> PrincipalOut:
    try:
        clearance = validate_clearance(body.clearance)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422) from exc
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise AppError("用户不存在", status_code=404)
    user.clearance = clearance
    await session.flush()
    out = await load_principal(session, user_id)
    await session.commit()
    assert out is not None
    await write_audit(
        session,
        principal.tenant_id,
        action="user.clearance_update",
        resource_type="user",
        resource_id=user_id,
        detail={"clearance": clearance},
        actor=principal.username,
    )
    return _principal_out(out)


@router.post("/users/{user_id}/establishment", response_model=PrincipalOut)
async def set_establishment(
    user_id: str,
    body: EstablishmentRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> PrincipalOut:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise AppError("用户不存在", status_code=404)
    existing = (
        await session.execute(
            select(UserOrgRelation).where(
                UserOrgRelation.user_id == user_id,
                UserOrgRelation.org_unit_id == body.org_unit_id,
                UserOrgRelation.relation == RELATION_ESTABLISHMENT,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            UserOrgRelation(
                user_id=user_id,
                org_unit_id=body.org_unit_id,
                relation=RELATION_ESTABLISHMENT,
            )
        )
    await session.flush()
    out = await load_principal(session, user_id)
    await session.commit()
    assert out is not None
    await write_audit(
        session,
        principal.tenant_id,
        action="user.establishment_set",
        resource_type="user",
        resource_id=user_id,
        detail={"org_unit_id": body.org_unit_id},
        actor=principal.username,
    )
    return _principal_out(out)


@router.post("/users/{user_id}/deactivate", status_code=204)
async def deactivate_user(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_USERS_MANAGE)),
) -> None:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != principal.tenant_id:
        raise AppError("用户不存在", status_code=404)
    user.is_active = False
    await revoke_user_sessions(session, user_id)
    await session.commit()
