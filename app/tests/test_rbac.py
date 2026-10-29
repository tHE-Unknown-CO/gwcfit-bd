from types import SimpleNamespace

from app.models.enums import PermissionCode, RoleName
from app.permissions.rbac import DEVELOPER_ADMIN_PERMISSIONS, has_permission


def user(role: RoleName, overrides=None):
    return SimpleNamespace(role=role.value, permission_overrides=overrides or [])


def override(permission: PermissionCode, allowed: bool):
    return SimpleNamespace(permission=permission.value, allowed=allowed)


def test_trainer_cannot_manage_payments_by_default():
    assert not has_permission(user(RoleName.TRAINER), PermissionCode.MANAGE_PAYMENTS)


def test_receptionist_can_manage_front_desk_plans_trainers_and_payments():
    assert has_permission(user(RoleName.RECEPTIONIST), PermissionCode.MANAGE_TRAINERS)
    assert has_permission(
        user(RoleName.RECEPTIONIST), PermissionCode.MANAGE_MEMBERSHIP_PLANS
    )
    assert has_permission(user(RoleName.RECEPTIONIST), PermissionCode.MANAGE_PAYMENTS)


def test_sub_admin_permission_override_allows_member_management():
    sub_admin = user(RoleName.SUB_ADMIN, [override(PermissionCode.MANAGE_MEMBERS, True)])
    assert has_permission(sub_admin, PermissionCode.MANAGE_MEMBERS)


def test_owner_permission_override_can_revoke_specific_permission():
    owner = user(RoleName.GYM_OWNER, [override(PermissionCode.MANAGE_PAYMENTS, False)])
    assert not has_permission(owner, PermissionCode.MANAGE_PAYMENTS)


def test_developer_admin_has_full_platform_access():
    developer_admin = user(RoleName.SUPER_ADMIN)
    assert DEVELOPER_ADMIN_PERMISSIONS == set(PermissionCode)
    assert all(has_permission(developer_admin, permission) for permission in PermissionCode)
