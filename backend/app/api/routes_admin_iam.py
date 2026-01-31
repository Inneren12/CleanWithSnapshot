from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminRole, require_permission_keys
from app.api.org_context import require_org_context
from app.domain.iam import permissions as iam_permissions
from app.domain.iam.db_models import IamRole
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import Membership, MembershipRole, User
from app.infra.db import get_db_session

router = APIRouter(prefix="/v1/admin/iam", tags=["admin-iam"])


class PermissionCatalogEntry(BaseModel):
    key: str
    label: str
    description: str
    group: str | None = None


class PermissionCatalogResponse(BaseModel):
    permissions: list[PermissionCatalogEntry]


class RoleResponse(BaseModel):
    role_id: uuid.UUID | None = None
    key: str
    name: str
    description: str | None = None
    permissions: list[str]
    builtin: bool


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]


class RoleCreateRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]
    key: str | None = None


class RoleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class AdminIAMUserResponse(BaseModel):
    membership_id: int
    user_id: uuid.UUID
    email: str
    role: MembershipRole
    role_key: str
    custom_role_id: uuid.UUID | None = None
    membership_active: bool
    user_active: bool
    must_change_password: bool


class AdminIAMUserListResponse(BaseModel):
    users: list[AdminIAMUserResponse]


class AdminIAMUserRoleUpdateRequest(BaseModel):
    role: MembershipRole | None = None
    custom_role_id: uuid.UUID | None = None


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _validate_permissions(keys: list[str]) -> list[str]:
    normalized = iam_permissions.normalize_permission_keys(keys)
    unknown = [key for key in normalized if key not in iam_permissions.PERMISSION_KEYS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown permissions: {', '.join(unknown)}",
        )
    return normalized


async def _require_owner(
    identity: AdminIdentity = Depends(require_permission_keys("users.manage")),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


@router.get("/permissions", response_model=PermissionCatalogResponse)
async def list_permissions(
    _identity: AdminIdentity = Depends(require_permission_keys("users.manage")),
) -> PermissionCatalogResponse:
    return PermissionCatalogResponse(
        permissions=[
            PermissionCatalogEntry(
                key=entry.key,
                label=entry.label,
                description=entry.description,
                group=entry.group,
            )
            for entry in iam_permissions.PERMISSION_CATALOG
        ]
    )


@router.get("/roles", response_model=RoleListResponse)
async def list_roles(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("users.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> RoleListResponse:
    result = await session.execute(
        sa.select(IamRole).where(IamRole.org_id == org_id).order_by(IamRole.name)
    )
    custom_roles = [
        RoleResponse(
            role_id=role.role_id,
            key=role.role_key,
            name=role.name,
            description=role.description,
            permissions=iam_permissions.normalize_permission_keys(role.permissions),
            builtin=False,
        )
        for role in result.scalars().all()
    ]
    builtins = [
        RoleResponse(
            role_id=None,
            key=role.key,
            name=role.name,
            description=role.description,
            permissions=sorted(role.permissions),
            builtin=True,
        )
        for role in iam_permissions.builtin_roles()
    ]
    return RoleListResponse(roles=builtins + custom_roles)


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(_require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    permissions = _validate_permissions(payload.permissions)
    role_key = _slugify(payload.key or payload.name)
    if not role_key:
        raise HTTPException(status_code=422, detail="Role key required")
    builtin_keys = {role.key for role in iam_permissions.builtin_roles()}
    if role_key in builtin_keys:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role key reserved")
    existing = await session.scalar(
        sa.select(IamRole).where(IamRole.org_id == org_id, IamRole.role_key == role_key)
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role key already exists")
    role = IamRole(
        org_id=org_id,
        role_key=role_key,
        name=payload.name.strip(),
        description=payload.description,
        permissions=permissions,
    )
    session.add(role)
    await session.commit()
    return RoleResponse(
        role_id=role.role_id,
        key=role.role_key,
        name=role.name,
        description=role.description,
        permissions=permissions,
        builtin=False,
    )


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(_require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    role = await session.get(IamRole, role_id)
    if not role or role.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if payload.name:
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        role.permissions = _validate_permissions(payload.permissions)
    session.add(role)
    await session.commit()
    return RoleResponse(
        role_id=role.role_id,
        key=role.role_key,
        name=role.name,
        description=role.description,
        permissions=iam_permissions.normalize_permission_keys(role.permissions),
        builtin=False,
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_200_OK)
async def delete_role(
    role_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(_require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    role = await session.get(IamRole, role_id)
    if not role or role.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    memberships = await session.execute(
        sa.select(Membership.user_id).where(Membership.custom_role_id == role_id)
    )
    user_ids = [row[0] for row in memberships.all()]
    await session.execute(
        sa.update(Membership)
        .where(Membership.custom_role_id == role_id)
        .values(custom_role_id=None)
    )
    for user_id in user_ids:
        await saas_service.revoke_user_sessions_for_org(
            session, user_id, org_id, reason="custom_role_deleted"
        )
    await session.delete(role)
    await session.commit()
    return {"status": "deleted"}


@router.get("/users", response_model=AdminIAMUserListResponse)
async def list_admin_users(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("users.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> AdminIAMUserListResponse:
    result = await session.execute(
        sa.select(Membership, User, IamRole.role_key)
        .join(User, User.user_id == Membership.user_id)
        .outerjoin(IamRole, IamRole.role_id == Membership.custom_role_id)
        .where(Membership.org_id == org_id)
    )
    users = [
        AdminIAMUserResponse(
            membership_id=membership.membership_id,
            user_id=user.user_id,
            email=user.email,
            role=membership.role,
            role_key=role_key or membership.role.value,
            custom_role_id=membership.custom_role_id,
            membership_active=membership.is_active,
            user_active=user.is_active,
            must_change_password=bool(user.must_change_password),
        )
        for membership, user, role_key in result.all()
    ]
    return AdminIAMUserListResponse(users=users)


@router.patch("/users/{user_id}/role", response_model=AdminIAMUserResponse)
async def update_admin_user_role(
    user_id: uuid.UUID,
    payload: AdminIAMUserRoleUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("users.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> AdminIAMUserResponse:
    membership = await session.scalar(
        sa.select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )
    user = await session.get(User, user_id)
    if not membership or not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not payload.role and not payload.custom_role_id:
        raise HTTPException(status_code=422, detail="Role required")

    if payload.custom_role_id:
        role_record = await session.get(IamRole, payload.custom_role_id)
        if not role_record or role_record.org_id != org_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        membership.custom_role_id = role_record.role_id
    else:
        membership.custom_role_id = None

    if payload.role:
        await saas_service.update_membership_role(session, membership, payload.role)
    else:
        await saas_service.revoke_user_sessions_for_org(
            session, membership.user_id, membership.org_id, reason="role_changed"
        )
    await session.commit()
    role_key = await session.scalar(
        sa.select(IamRole.role_key).where(IamRole.role_id == membership.custom_role_id)
    )
    return AdminIAMUserResponse(
        membership_id=membership.membership_id,
        user_id=user.user_id,
        email=user.email,
        role=membership.role,
        role_key=role_key or membership.role.value,
        custom_role_id=membership.custom_role_id,
        membership_active=membership.is_active,
        user_active=user.is_active,
        must_change_password=bool(user.must_change_password),
    )
