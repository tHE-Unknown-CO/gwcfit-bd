from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import InvitationStatus, RoleName
from app.services.invitations import _read


def test_invitation_read_never_re_exposes_the_bearer_token():
    now = datetime.now(UTC)
    invitation = SimpleNamespace(
        id=uuid4(),
        gym_id=uuid4(),
        gym=None,
        role=RoleName.MEMBER.value,
        email="member@example.com",
        status=InvitationStatus.ACTIVE.value,
        expires_at=now + timedelta(hours=1),
        use_count=0,
        max_uses=1,
        created_at=now,
        created_by=uuid4(),
        used_at=None,
        used_by=None,
    )

    result = _read(invitation)  # type: ignore[arg-type]
    assert result.token is None
