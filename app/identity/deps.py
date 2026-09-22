from __future__ import annotations

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.errors import AppError
from app.identity.constants import SESSION_COOKIE_NAME
from app.identity.loader import load_principal
from app.identity.principal import Principal
from app.identity.sessions import get_session_by_token


async def get_optional_principal(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    kb_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Principal | None:
    token = kb_session
    if not token:
        return None
    session = await get_session_by_token(db, token)
    if session is None:
        return None
    principal = await load_principal(db, session.user_id)
    if principal is None:
        return None
    request.state.principal = principal
    return principal


async def get_current_principal(
    principal: Principal | None = Depends(get_optional_principal),
) -> Principal:
    if principal is None:
        raise AppError("未登录或会话已失效", status_code=401)
    return principal


_permission_deps: dict[str, object] = {}


def require_permission(code: str):
    cached = _permission_deps.get(code)
    if cached is not None:
        return cached

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_permission(code):
            raise AppError("缺少所需权限", status_code=403)
        return principal

    _permission_deps[code] = _dep
    return _dep


def require_any_permission(*codes: str):
    key = "|".join(sorted(codes))
    cached = _permission_deps.get(key)
    if cached is not None:
        return cached

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not any(principal.has_permission(code) for code in codes):
            raise AppError("缺少所需权限", status_code=403)
        return principal

    _permission_deps[key] = _dep
    return _dep


async def tenant_from_principal(
    principal: Principal = Depends(get_current_principal),
) -> str:
    """Replace header-based tenant resolution."""
    from app.core.tenant import set_current_tenant

    set_current_tenant(principal.tenant_id)
    return principal.tenant_id
