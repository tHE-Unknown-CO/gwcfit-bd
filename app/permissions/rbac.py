from collections.abc import Iterable

from app.models.enums import PermissionCode, RoleName
from app.models.user import User

OWNER_PERMISSIONS = {
    PermissionCode.CONFIGURE_GYM,
    PermissionCode.MANAGE_ATTENDANCE,
    PermissionCode.MANAGE_DIET_PLANS,
    PermissionCode.MANAGE_MEMBERS,
    PermissionCode.MANAGE_MEMBERSHIP_PLANS,
    PermissionCode.MANAGE_PAYMENTS,
    PermissionCode.MANAGE_REPORTS,
    PermissionCode.MANAGE_STAFF,
    PermissionCode.MANAGE_TRAINERS,
    PermissionCode.MANAGE_WORKOUTS,
    PermissionCode.VIEW_OWN_PROFILE,
}

# The developer admin is the platform-level super admin. Keep this explicit so
# the access contract is easy to audit and cannot drift from the API surface.
DEVELOPER_ADMIN_PERMISSIONS = set(PermissionCode)

ROLE_PERMISSIONS: dict[RoleName, set[PermissionCode]] = {
    RoleName.SUPER_ADMIN: DEVELOPER_ADMIN_PERMISSIONS,
    RoleName.GYM_OWNER: OWNER_PERMISSIONS,
    RoleName.SUB_ADMIN: {PermissionCode.VIEW_OWN_PROFILE},
    RoleName.TRAINER: {
        PermissionCode.MANAGE_ATTENDANCE,
        PermissionCode.MANAGE_WORKOUTS,
        PermissionCode.MANAGE_DIET_PLANS,
        PermissionCode.VIEW_OWN_PROFILE,
    },
    RoleName.RECEPTIONIST: {
        PermissionCode.MANAGE_ATTENDANCE,
        PermissionCode.MANAGE_MEMBERS,
        PermissionCode.MANAGE_PAYMENTS,
        PermissionCode.VIEW_OWN_PROFILE,
    },
    RoleName.MEMBER: {PermissionCode.VIEW_OWN_PROFILE},
}


def normalize_role(role: str | RoleName) -> RoleName:
    return role if isinstance(role, RoleName) else RoleName(role)


def get_effective_permissions(user: User) -> set[PermissionCode]:
    role = normalize_role(user.role)
    permissions = set(ROLE_PERMISSIONS.get(role, set()))

    for override in getattr(user, "permission_overrides", []):
        code = PermissionCode(override.permission)
        if override.allowed:
            permissions.add(code)
        else:
            permissions.discard(code)

    return permissions


def has_permission(user: User, permission: PermissionCode) -> bool:
    if normalize_role(user.role) == RoleName.SUPER_ADMIN:
        return True
    return permission in get_effective_permissions(user)


def has_any_permission(user: User, permissions: Iterable[PermissionCode]) -> bool:
    return any(has_permission(user, permission) for permission in permissions)
