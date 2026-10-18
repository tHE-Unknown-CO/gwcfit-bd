from uuid import UUID

from pydantic import EmailStr

from app.models.enums import RoleName
from app.schemas.common import EnterpriseRead


class StaffUserRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    email: EmailStr
    full_name: str
    role: RoleName
    phone: str | None
    is_email_verified: bool
