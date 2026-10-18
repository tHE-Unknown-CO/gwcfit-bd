from typing import Any, Generic, TypeVar
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], db: Session, gym_id: UUID):
        self.model = model
        self.db = db
        self.gym_id = gym_id

    def base_query(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(
            getattr(self.model, "gym_id") == self.gym_id,
            getattr(self.model, "is_active").is_(True),
        )

    def list(self, *, skip: int = 0, limit: int = 50) -> list[ModelT]:
        statement = self.base_query().order_by(self.model.created_at.desc(), self.model.id).offset(skip).limit(min(limit, 200))
        return list(self.db.scalars(statement).all())

    def get(self, resource_id: UUID) -> ModelT | None:
        statement = self.base_query().where(getattr(self.model, "id") == resource_id)
        return self.db.scalar(statement)

    def create(self, payload: dict[str, Any], *, actor_id: UUID | None = None) -> ModelT:
        self._validate_payload(payload)
        record = self.model(**payload, gym_id=self.gym_id, created_by=actor_id, updated_by=actor_id)
        self.db.add(record)
        self._commit()
        self.db.refresh(record)
        return record

    def update(self, record: ModelT, payload: dict[str, Any], *, actor_id: UUID | None = None) -> ModelT:
        self._validate_payload(payload, record)
        for key, value in payload.items():
            setattr(record, key, value)
        if actor_id is not None:
            setattr(record, "updated_by", actor_id)
        self._commit()
        self.db.refresh(record)
        return record

    def deactivate(self, record: ModelT, *, actor_id: UUID | None = None) -> ModelT:
        setattr(record, "is_active", False)
        if actor_id is not None:
            setattr(record, "updated_by", actor_id)
        self._commit()
        self.db.refresh(record)
        return record

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="This change conflicts with an existing record.") from exc

    def _validate_payload(self, payload: dict[str, Any], record: ModelT | None = None) -> None:
        """Validate the final record before mutating it or writing cross-tenant links."""
        from app.models.enums import RoleName
        from app.models.member import Member
        from app.models.plans import MembershipPlan
        from app.models.trainer import Trainer
        from app.models.user import User

        columns = inspect(self.model).column_attrs
        for key, value in payload.items():
            if value is None and key in columns and not columns[key].columns[0].nullable:
                raise HTTPException(status_code=422, detail=f"{key} cannot be null.")

        for start_key, end_key in (
            ("starts_at", "ends_at"),
            ("membership_starts_at", "membership_ends_at"),
            ("check_in_at", "check_out_at"),
        ):
            if start_key not in payload and end_key not in payload:
                continue
            start = payload.get(start_key, getattr(record, start_key, None))
            end = payload.get(end_key, getattr(record, end_key, None))
            if start is not None and end is not None and end < start:
                raise HTTPException(status_code=422, detail=f"{end_key} must be on or after {start_key}.")

        relations = {
            "member_id": (Member, "Member"),
            "trainer_id": (Trainer, "Trainer"),
            "membership_plan_id": (MembershipPlan, "Membership plan"),
            "user_id": (User, "User"),
        }
        for key, (model, label) in relations.items():
            resource_id = payload.get(key)
            if resource_id is None:
                continue
            statement = select(model.id).where(
                model.id == resource_id, model.gym_id == self.gym_id, model.is_active.is_(True),
            )
            if key == "user_id":
                role = RoleName.MEMBER if self.model is Member else RoleName.TRAINER
                statement = statement.where(User.role == role.value)
            if self.db.scalar(statement) is None:
                raise HTTPException(status_code=400, detail=f"{label} must belong to the current gym.")
            if key == "user_id":
                linked = select(self.model.id).where(self.model.user_id == resource_id)
                if record is not None:
                    linked = linked.where(self.model.id != record.id)
                if self.db.scalar(linked) is not None:
                    raise HTTPException(status_code=409, detail="User already has a linked profile.")
