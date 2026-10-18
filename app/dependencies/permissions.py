from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.dependencies.auth import get_current_user
from app.models.enums import PermissionCode, RoleName
from app.models.user import User
from app.permissions.rbac import has_permission


def require_roles(*roles: RoleName) -> Callable:
    allowed = {role.value for role in roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not allowed.")
        return current_user

    return dependency


def require_permission(permission: PermissionCode) -> Callable:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission is not allowed.")
        return current_user

    return dependency


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != RoleName.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access is required.")
    return current_user


def require_gym_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != RoleName.GYM_OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin access is required.")
    if current_user.gym_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin is not linked to a gym.")
    return current_user


def require_member(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != RoleName.MEMBER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member access is required.")
    if current_user.gym_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member is not linked to a gym.")
    return current_user
