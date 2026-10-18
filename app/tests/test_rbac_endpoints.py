from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.models.enums import GymStatus, InvitationStatus, PermissionCode, RoleName
from app.models.billing import Subscription
from app.models.gym import Gym
from app.models.gym_inquiry import GymInquiry
from app.models.invitation import Invitation
from app.models.login_event import LoginEvent
from app.models.member import Member
from app.models.platform_plan import PlatformPlan
from app.models.trainer import Trainer
from app.models.user import User


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeExecuteResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *, scalar_results=None, scalars_results=None, execute_results=None):
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.execute_results = list(execute_results or [])
        self.added = []
        self.committed = False
        self.rolled_back = False

    def scalar(self, _statement):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    def scalars(self, _statement):
        if self.scalars_results:
            return FakeScalarResult(self.scalars_results.pop(0))
        return FakeScalarResult([])

    def execute(self, _statement):
        if self.execute_results:
            return FakeExecuteResult(self.execute_results.pop(0))
        return FakeExecuteResult([])

    def add(self, record):
        self._apply_defaults(record)
        self.added.append(record)

    def flush(self):
        for record in self.added:
            self._apply_defaults(record)

    def commit(self):
        self.flush()
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, record):
        self._apply_defaults(record)

    def _apply_defaults(self, record):
        now = datetime.now(UTC)
        if getattr(record, "id", None) is None:
            record.id = uuid4()
        if getattr(record, "created_at", None) is None:
            record.created_at = now
        if getattr(record, "updated_at", None) is None:
            record.updated_at = now
        if getattr(record, "is_active", None) is None:
            record.is_active = True
        if isinstance(record, Gym) and getattr(record, "settings", None) is None:
            record.settings = {}
        if isinstance(record, Gym) and getattr(record, "status", None) is None:
            record.status = GymStatus.ACTIVE.value
        if isinstance(record, User) and getattr(record, "profile", None) is None:
            record.profile = {}
        if isinstance(record, GymInquiry) and getattr(record, "status", None) is None:
            record.status = "new"


def permission_override(permission: PermissionCode, allowed: bool = True):
    return SimpleNamespace(permission=permission.value, allowed=allowed)


def make_user(role: RoleName, *, gym_id=None, overrides=None):
    return SimpleNamespace(
        id=uuid4(),
        gym_id=gym_id,
        role=role.value,
        email=f"{role.value}-{uuid4()}@example.com",
        full_name=f"{role.value} User",
        is_active=True,
        permission_overrides=overrides or [],
    )


def make_db_user(role: RoleName, *, gym_id, full_name=None, email=None):
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        gym_id=gym_id,
        email=email or f"{role.value}-{uuid4()}@example.com",
        hashed_password="hashed",
        full_name=full_name or f"{role.value} User",
        role=role.value,
        phone=None,
        is_email_verified=False,
        profile={},
        created_at=now,
        updated_at=now,
        created_by=None,
        updated_by=None,
        is_active=True,
    )


def make_gym(*, gym_id=None):
    now = datetime.now(UTC)
    return Gym(
        id=gym_id or uuid4(),
        name="PulseFit Downtown",
        code="PULS-123456",
        status=GymStatus.ACTIVE.value,
        email="owner@example.com",
        phone=None,
        address=None,
        timezone="UTC",
        settings={},
        created_at=now,
        updated_at=now,
        created_by=None,
        updated_by=None,
        is_active=True,
    )


def make_member(*, gym_id, member_id=None, user_id=None):
    now = datetime.now(UTC)
    member = Member(
        id=member_id or uuid4(),
        gym_id=gym_id,
        user_id=user_id,
        trainer_id=None,
        membership_plan_id=None,
        member_code="MBR-001",
        first_name="Alex",
        last_name="Member",
        email="alex@example.com",
        phone="555-0100",
        status="active",
        joined_at=now,
        membership_starts_at=None,
        membership_ends_at=None,
        emergency_contact={},
        extra_data={},
        created_at=now,
        updated_at=now,
        created_by=None,
        updated_by=None,
        is_active=True,
    )
    return member


def make_invitation(*, gym, role):
    now = datetime.now(UTC)
    invitation = Invitation(
        id=uuid4(), gym_id=gym.id, role=role.value, email=None,
        token_hash="sha256$test", status=InvitationStatus.ACTIVE.value,
        expires_at=now.replace(year=now.year + 1), max_uses=1, use_count=0,
        used_at=None, used_by=None, created_at=now, updated_at=now,
        created_by=uuid4(), updated_by=uuid4(), is_active=True,
    )
    invitation.gym = gym
    return invitation


def make_platform_plan():
    now = datetime.now(UTC)
    return PlatformPlan(
        id=uuid4(), slug="launch", name="Launch", description="For independent gyms",
        price_cents=199900, currency="INR", billing_period="month",
        member_limit="Up to 150 members", features=["Member management"],
        cta_label="Start free", trial_days=30, is_popular=False, display_order=1,
        created_at=now, updated_at=now, created_by=None, updated_by=None, is_active=True,
    )


@contextmanager
def client_as(user, db):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_super_admin_creates_gym_admin():
    super_admin = make_user(RoleName.SUPER_ADMIN)
    db = FakeSession(scalar_results=[None, None])

    with client_as(super_admin, db) as client:
        response = client.post(
            "/api/v1/super-admin/gym-admin",
            json={
                "gym_name": "PulseFit Downtown",
                "gym_email": "downtown@example.com",
                "admin_full_name": "Olivia Owner",
                "admin_email": "owner@example.com",
                "admin_password": "securepass123",
            },
        )

    assert response.status_code == 201
    assert response.json()["gym_admin"]["role"] == RoleName.GYM_OWNER.value
    assert len(db.added) == 2
    assert isinstance(db.added[0], Gym)
    assert isinstance(db.added[1], User)
    assert db.added[1].gym_id == db.added[0].id
    assert db.added[1].role == RoleName.GYM_OWNER.value


def test_member_registration_creates_linked_member_profile_for_selected_gym():
    gym = make_gym()
    invitation = make_invitation(gym=gym, role=RoleName.MEMBER)
    db = FakeSession(scalar_results=[None, invitation, gym, gym, None, None])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "gym_id": str(gym.id),
                "gym_name": gym.name,
                "full_name": "Ava Stone",
                "email": "ava@example.com",
                "password": "securepass123",
                "role": "member",
                "invitation_token": "test-invitation-token-1234567890",
            },
        )

    assert response.status_code == 201
    user = next(record for record in db.added if isinstance(record, User))
    member = next(record for record in db.added if isinstance(record, Member))
    assert isinstance(user, User)
    assert isinstance(member, Member)
    assert user.gym_id == gym.id
    assert member.gym_id == gym.id
    assert member.user_id == user.id
    assert member.member_code == f"MBR-{user.id.hex.upper()}"
    assert member.first_name == "Ava"
    assert member.last_name == "Stone"
    assert member.email == "ava@example.com"


def test_member_registration_links_existing_unlinked_member_profile_by_email():
    gym = make_gym()
    existing_member = make_member(gym_id=gym.id)
    existing_member.email = "ava@example.com"
    existing_member.user_id = None
    invitation = make_invitation(gym=gym, role=RoleName.MEMBER)
    db = FakeSession(scalar_results=[None, invitation, gym, gym, None, existing_member])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "gym_id": str(gym.id),
                "gym_name": gym.name,
                "full_name": "Ava Stone",
                "email": "ava@example.com",
                "password": "securepass123",
                "role": "member",
                "invitation_token": "test-invitation-token-1234567890",
            },
        )

    assert response.status_code == 201
    user = next(record for record in db.added if isinstance(record, User))
    assert existing_member.user_id == user.id
    assert existing_member.updated_by == user.id


def test_trainer_registration_creates_linked_trainer_profile_for_selected_gym():
    gym = make_gym()
    invitation = make_invitation(gym=gym, role=RoleName.TRAINER)
    db = FakeSession(scalar_results=[None, invitation, gym, gym, None, None])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "gym_id": str(gym.id),
                "gym_name": gym.name,
                "full_name": "Tara Coach",
                "email": "tara@example.com",
                "password": "securepass123",
                "role": "trainer",
                "invitation_token": "test-invitation-token-1234567890",
            },
        )

    assert response.status_code == 201
    user = next(record for record in db.added if isinstance(record, User))
    trainer = next(record for record in db.added if isinstance(record, Trainer))
    assert isinstance(user, User)
    assert isinstance(trainer, Trainer)
    assert user.gym_id == gym.id
    assert trainer.gym_id == gym.id
    assert trainer.user_id == user.id
    assert trainer.full_name == "Tara Coach"
    assert trainer.email == "tara@example.com"


def test_gym_owner_lists_registered_gym_users_by_role():
    gym_id = uuid4()
    gym_owner = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    db = FakeSession(
        scalars_results=[
            [
                make_db_user(RoleName.MEMBER, gym_id=gym_id, full_name="Ava Stone", email="ava@example.com"),
                make_db_user(RoleName.TRAINER, gym_id=gym_id, full_name="Tara Coach", email="tara@example.com"),
                make_db_user(RoleName.RECEPTIONIST, gym_id=gym_id, full_name="Riya Desk", email="riya@example.com"),
                make_db_user(RoleName.SUB_ADMIN, gym_id=gym_id, full_name="Sam Admin", email="sam@example.com"),
            ]
        ]
    )

    with client_as(gym_owner, db) as client:
        response = client.get("/api/v1/staff")

    assert response.status_code == 200
    roles = {user["role"] for user in response.json()}
    assert roles == {
        RoleName.MEMBER.value,
        RoleName.TRAINER.value,
        RoleName.RECEPTIONIST.value,
        RoleName.SUB_ADMIN.value,
    }


def test_gym_admin_creates_user_under_own_gym():
    gym = make_gym()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym.id)
    db = FakeSession(scalar_results=[gym, None, None, None])

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "name": "Maya Singh",
                "email": "maya-user@example.com",
                "password": "securepass123",
                "phone": "555-0101",
                "role": "member",
            },
        )

    assert response.status_code == 201
    assert len(db.added) == 2
    user = db.added[0]
    member = db.added[1]
    assert isinstance(user, User)
    assert isinstance(member, Member)
    assert user.gym_id == gym.id
    assert member.gym_id == gym.id
    assert member.user_id == user.id
    assert response.json()["gym_id"] == str(gym.id)
    assert response.json()["status"] == "active"


def test_gym_admin_creates_every_managed_role_under_own_gym():
    cases = (
        (RoleName.MEMBER, Member, [None, None]),
        (RoleName.TRAINER, Trainer, [None, None]),
        (RoleName.RECEPTIONIST, None, []),
        (RoleName.SUB_ADMIN, None, []),
    )

    for role, expected_profile_type, profile_scalar_results in cases:
        gym = make_gym()
        gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym.id)
        db = FakeSession(scalar_results=[gym, None, *profile_scalar_results])

        with client_as(gym_admin, db) as client:
            response = client.post(
                "/api/v1/users",
                json={
                    "name": f"{role.value.title()} User",
                    "email": f"{role.value}-{uuid4()}@example.com",
                    "password": "securepass123",
                    "phone": "555-0102",
                    "role": role.value,
                },
            )

        assert response.status_code == 201
        assert db.added[0].gym_id == gym.id
        assert db.added[0].role == role.value
        assert response.json()["gym_id"] == str(gym.id)
        assert response.json()["role"] == role.value
        if expected_profile_type is None:
            assert len(db.added) == 1
        else:
            assert len(db.added) == 2
            assert isinstance(db.added[1], expected_profile_type)
            assert db.added[1].gym_id == gym.id
            assert db.added[1].user_id == db.added[0].id


def test_gym_admin_cannot_create_user_for_another_gym():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "gym_id": str(uuid4()),
                "name": "Maya Singh",
                "email": "maya-other@example.com",
                "password": "securepass123",
                "role": "member",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot create users for another gym."
    assert db.added == []


def test_gym_admin_cannot_create_super_admin_user():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "name": "Platform Admin",
                "email": "platform-admin@example.com",
                "password": "securepass123",
                "role": "super_admin",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Gym Admin can create only gym user roles."
    assert db.added == []


def test_gym_admin_cannot_create_another_gym_owner():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "name": "Other Owner",
                "email": "other-owner-create@example.com",
                "password": "securepass123",
                "role": "gym_owner",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Gym Admin can create only gym user roles."
    assert db.added == []


def test_gym_admin_cannot_list_another_gym_users():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.get(f"/api/v1/users?gym_id={uuid4()}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot view users for another gym."


def test_gym_admin_cannot_filter_unmanaged_user_role():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.get("/api/v1/users?role=gym_owner")

    assert response.status_code == 400
    assert response.json()["detail"] == "Role filter is not allowed."


def test_gym_admin_lists_users_for_own_gym_with_role_filter():
    gym_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    db = FakeSession(
        scalars_results=[
            [
                make_db_user(RoleName.TRAINER, gym_id=gym_id, full_name="Tara Coach", email="tara-user@example.com"),
            ]
        ]
    )

    with client_as(gym_admin, db) as client:
        response = client.get("/api/v1/users?role=trainer")

    assert response.status_code == 200
    assert response.json()[0]["role"] == RoleName.TRAINER.value
    assert response.json()[0]["gym_id"] == str(gym_id)


def test_sub_admin_with_staff_permission_lists_only_gym_users():
    gym_id = uuid4()
    sub_admin = make_user(
        RoleName.SUB_ADMIN,
        gym_id=gym_id,
        overrides=[permission_override(PermissionCode.MANAGE_STAFF)],
    )
    db = FakeSession(
        scalars_results=[
            [
                make_db_user(RoleName.MEMBER, gym_id=gym_id, full_name="Ava Stone", email="ava-subadmin@example.com"),
                make_db_user(RoleName.RECEPTIONIST, gym_id=gym_id, full_name="Riya Desk", email="riya-subadmin@example.com"),
            ]
        ]
    )

    with client_as(sub_admin, db) as client:
        response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert {user["role"] for user in response.json()} == {RoleName.MEMBER.value, RoleName.RECEPTIONIST.value}
    assert {user["gym_id"] for user in response.json()} == {str(gym_id)}


def test_sub_admin_without_staff_permission_cannot_manage_users():
    sub_admin = make_user(RoleName.SUB_ADMIN, gym_id=uuid4())
    db = FakeSession()

    with client_as(sub_admin, db) as client:
        response = client.get("/api/v1/users")

    assert response.status_code == 403
    assert response.json()["detail"] == "User management access is required."


def test_gym_admin_counts_users_for_own_gym():
    gym_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    db = FakeSession(
        execute_results=[
            [
                (RoleName.MEMBER.value, 3),
                (RoleName.TRAINER.value, 2),
                (RoleName.RECEPTIONIST.value, 1),
                (RoleName.SUB_ADMIN.value, 1),
            ]
        ]
    )

    with client_as(gym_admin, db) as client:
        response = client.get("/api/v1/users/counts")

    assert response.status_code == 200
    assert response.json() == {
        "total": 7,
        "member": 3,
        "trainer": 2,
        "receptionist": 1,
        "sub_admin": 1,
        "gym_owner": 0,
    }


def test_gym_admin_cannot_count_another_gym_users():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.get(f"/api/v1/users/counts?gym_id={uuid4()}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot view users for another gym."


def test_super_admin_lists_users_across_gyms():
    gym_one_id = uuid4()
    gym_two_id = uuid4()
    super_admin = make_user(RoleName.SUPER_ADMIN)
    db = FakeSession(
        scalars_results=[
            [
                make_db_user(RoleName.MEMBER, gym_id=gym_one_id, full_name="ZE Member", email="ze-member@example.com"),
                make_db_user(RoleName.TRAINER, gym_id=gym_two_id, full_name="Other Trainer", email="other-trainer@example.com"),
                make_db_user(RoleName.GYM_OWNER, gym_id=gym_two_id, full_name="Other Owner", email="other-owner@example.com"),
            ]
        ]
    )

    with client_as(super_admin, db) as client:
        response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert {user["gym_id"] for user in response.json()} == {str(gym_one_id), str(gym_two_id)}
    assert {user["role"] for user in response.json()} == {
        RoleName.MEMBER.value,
        RoleName.TRAINER.value,
        RoleName.GYM_OWNER.value,
    }


def test_super_admin_counts_users_across_gyms():
    super_admin = make_user(RoleName.SUPER_ADMIN)
    db = FakeSession(
        execute_results=[
            [
                (RoleName.MEMBER.value, 4),
                (RoleName.TRAINER.value, 2),
                (RoleName.GYM_OWNER.value, 2),
            ]
        ]
    )

    with client_as(super_admin, db) as client:
        response = client.get("/api/v1/users/counts")

    assert response.status_code == 200
    assert response.json()["total"] == 8
    assert response.json()["member"] == 4
    assert response.json()["trainer"] == 2
    assert response.json()["gym_owner"] == 2


def test_gym_admin_update_can_clear_optional_phone():
    gym = make_gym()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym.id)
    user = make_db_user(RoleName.RECEPTIONIST, gym_id=gym.id, full_name="Riya Desk", email="riya-phone@example.com")
    user.phone = "555-0103"
    db = FakeSession(scalar_results=[user, gym])

    with client_as(gym_admin, db) as client:
        response = client.patch(f"/api/v1/users/{user.id}", json={"phone": None})

    assert response.status_code == 200
    assert user.phone is None
    assert response.json()["phone"] is None


def test_gym_admin_cannot_update_user_from_another_gym():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    other_user_id = uuid4()
    db = FakeSession(scalar_results=[None, other_user_id])

    with client_as(gym_admin, db) as client:
        response = client.patch(f"/api/v1/users/{other_user_id}", json={"name": "Blocked User"})

    assert response.status_code == 403


def test_gym_admin_deactivates_own_gym_user():
    gym_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    user = make_db_user(RoleName.RECEPTIONIST, gym_id=gym_id, full_name="Riya Desk", email="riya-user@example.com")
    db = FakeSession(scalar_results=[user])

    with client_as(gym_admin, db) as client:
        response = client.delete(f"/api/v1/users/{user.id}")

    assert response.status_code == 200
    assert user.is_active is False
    assert user.updated_by == gym_admin.id


def test_super_admin_creates_gym_owner_for_existing_gym():
    gym = make_gym()
    super_admin = make_user(RoleName.SUPER_ADMIN)
    db = FakeSession(scalar_results=[gym, None])

    with client_as(super_admin, db) as client:
        response = client.post(
            "/api/v1/users",
            json={
                "gym_id": str(gym.id),
                "name": "Owner Two",
                "email": "owner-two@example.com",
                "password": "securepass123",
                "role": "gym_owner",
            },
        )

    assert response.status_code == 201
    assert len(db.added) == 1
    assert db.added[0].gym_id == gym.id
    assert db.added[0].role == RoleName.GYM_OWNER.value


def test_gym_admin_creates_own_gym_member():
    gym_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    db = FakeSession(scalar_results=[None])

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/members",
            json={
                "member_code": "MBR-100",
                "first_name": "Maya",
                "last_name": "Singh",
                "email": "maya@example.com",
            },
        )

    assert response.status_code == 201
    assert len(db.added) == 1
    assert db.added[0].gym_id == gym_id
    assert db.added[0].created_by == gym_admin.id


def test_member_profile_auto_created_when_missing():
    gym = make_gym()
    member_user = make_user(RoleName.MEMBER, gym_id=gym.id)
    db = FakeSession(scalar_results=[None, gym, None, None])

    with client_as(member_user, db) as client:
        response = client.get("/api/v1/members/me")

    assert response.status_code == 200
    assert len(db.added) == 1
    member = db.added[0]
    assert isinstance(member, Member)
    assert member.gym_id == gym.id
    assert member.user_id == member_user.id
    assert member.email == member_user.email
    assert response.json()["user_id"] == str(member_user.id)


def test_gym_admin_updates_own_gym_member():
    gym_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    member = make_member(gym_id=gym_id)
    db = FakeSession(scalar_results=[member])

    with client_as(gym_admin, db) as client:
        response = client.patch(f"/api/v1/members/{member.id}", json={"first_name": "Mira"})

    assert response.status_code == 200
    assert response.json()["first_name"] == "Mira"
    assert member.updated_by == gym_admin.id


def test_gym_admin_updates_own_gym_member_trainer_assignment():
    gym_id = uuid4()
    trainer_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    member = make_member(gym_id=gym_id)
    db = FakeSession(scalar_results=[member, trainer_id])

    with client_as(gym_admin, db) as client:
        response = client.patch(f"/api/v1/members/{member.id}", json={"trainer_id": str(trainer_id)})

    assert response.status_code == 200
    assert response.json()["trainer_id"] == str(trainer_id)
    assert member.trainer_id == trainer_id
    assert member.updated_by == gym_admin.id


def test_gym_admin_cannot_assign_member_to_trainer_outside_current_gym():
    gym_id = uuid4()
    other_trainer_id = uuid4()
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=gym_id)
    member = make_member(gym_id=gym_id)
    db = FakeSession(scalar_results=[member, None])

    with client_as(gym_admin, db) as client:
        response = client.patch(f"/api/v1/members/{member.id}", json={"trainer_id": str(other_trainer_id)})

    assert response.status_code == 400
    assert response.json()["detail"] == "Trainer must belong to the current gym."
    assert member.trainer_id is None
    assert db.committed is False


def test_gym_admin_cannot_access_another_gym_member():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    other_member_id = uuid4()
    db = FakeSession(scalar_results=[None, other_member_id])

    with client_as(gym_admin, db) as client:
        response = client.get(f"/api/v1/members/{other_member_id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Member belongs to another gym."


def test_gym_admin_cannot_access_super_admin_apis():
    gym_admin = make_user(RoleName.GYM_OWNER, gym_id=uuid4())
    db = FakeSession()

    with client_as(gym_admin, db) as client:
        response = client.post(
            "/api/v1/super-admin/gym-admin",
            json={
                "gym_name": "Other Gym",
                "admin_full_name": "Other Owner",
                "admin_email": "other@example.com",
                "admin_password": "securepass123",
            },
        )

    assert response.status_code == 403
    assert db.added == []


def test_member_cannot_access_gym_admin_apis():
    member_user = make_user(RoleName.MEMBER, gym_id=uuid4())
    db = FakeSession()

    with client_as(member_user, db) as client:
        response = client.post(
            "/api/v1/members",
            json={
                "member_code": "MBR-200",
                "first_name": "Sam",
                "last_name": "Member",
            },
        )

    assert response.status_code == 403
    assert db.added == []


def test_public_platform_plans_are_available_without_authentication():
    plan = make_platform_plan()
    db = FakeSession(scalars_results=[[plan]])
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/platform-plans/public")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "launch"


def test_super_admin_can_update_platform_plan():
    plan = make_platform_plan()
    db = FakeSession(scalar_results=[plan])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.patch(
            f"/api/v1/platform-plans/{plan.id}",
            json={"price_cents": 249900, "is_popular": True},
        )

    assert response.status_code == 200
    assert response.json()["price_cents"] == 249900
    assert response.json()["is_popular"] is True
    assert db.committed is True
    assert db.added[0].action == "platform_plan.updated"


def test_gym_owner_cannot_update_platform_plan():
    plan = make_platform_plan()
    db = FakeSession(scalar_results=[plan])

    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.patch(
            f"/api/v1/platform-plans/{plan.id}",
            json={"price_cents": 249900},
        )

    assert response.status_code == 403
    assert db.committed is False


def test_platform_plan_update_rejects_null_required_field():
    plan = make_platform_plan()
    db = FakeSession(scalar_results=[plan])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.patch(f"/api/v1/platform-plans/{plan.id}", json={"name": None})

    assert response.status_code == 422
    assert db.committed is False


def test_public_owner_site_inquiry_is_saved_to_database():
    db = FakeSession()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/gym-inquiries", json={
                "full_name": "Arjun Kumar", "email": "arjun@example.com",
                "phone": "+91 98765 43210",
                "gym_name": "Arjun Fitness", "active_members_range": "100–300",
                "source": "owner_site",
            })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["status"] == "new"
    assert response.json()["phone"] == "+919876543210"
    assert isinstance(db.added[0], GymInquiry)
    assert db.committed is True


def test_owner_site_rejects_reused_inquiry_email():
    db = FakeSession(scalar_results=[uuid4()])
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/gym-inquiries", json={
                "full_name": "Arjun Kumar", "email": "arjun@example.com",
                "phone": "9876543210", "gym_name": "Arjun Fitness",
                "active_members_range": "100–300",
            })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert db.added == []


def test_owner_site_rejects_mobile_number_used_by_existing_user():
    db = FakeSession(scalar_results=[None, uuid4()])
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/gym-inquiries", json={
                "full_name": "Different Owner", "email": "different@example.com",
                "phone": "9876543210", "gym_name": "Different Fitness",
                "active_members_range": "Under 100",
            })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "mobile number" in response.json()["detail"]
    assert db.added == []


def test_non_developer_cannot_view_owner_inquiries():
    db = FakeSession()
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.get("/api/v1/developer/inquiries")
    assert response.status_code == 403


def test_developer_can_start_gym_free_trial():
    gym = make_gym()
    plan = make_platform_plan()
    db = FakeSession(scalar_results=[gym, plan, None])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.put(
            f"/api/v1/developer/gyms/{gym.id}/subscription",
            json={"platform_plan_id": str(plan.id), "status": "trialing"},
        )

    assert response.status_code == 200
    assert response.json()["plan_name"] == "Launch"
    assert response.json()["status"] == "trialing"
    assert any(isinstance(record, Subscription) for record in db.added)


def test_developer_can_view_login_history():
    event = LoginEvent(
        id=uuid4(), user_id=uuid4(), email="owner@example.com", role="super_admin",
        success=True, failure_reason=None, ip_address="127.0.0.1",
        user_agent="test-client", created_at=datetime.now(UTC),
    )
    db = FakeSession(scalars_results=[[event]])

    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.get("/api/v1/developer/login-events")

    assert response.status_code == 200
    assert response.json()[0]["success"] is True
    assert response.json()[0]["role"] == "super_admin"


def test_gym_owner_cannot_view_login_history():
    db = FakeSession()
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.get("/api/v1/developer/login-events")
    assert response.status_code == 403
