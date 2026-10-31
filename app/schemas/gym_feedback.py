from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GymFeedbackUpsert(BaseModel):
    rating: int = Field(ge=1, le=5)
    feedback_text: str | None = Field(default=None, max_length=1200)


class MemberGymFeedbackRead(BaseModel):
    id: UUID
    review_month: date
    rating: int
    feedback_text: str | None = None
    created_at: datetime
    updated_at: datetime


class GymFeedbackReview(MemberGymFeedbackRead):
    member_id: UUID
    member_name: str


class GymFeedbackSummary(BaseModel):
    average_rating: float = 0
    total_reviews: int = 0
    star_distribution: dict[int, int] = Field(default_factory=lambda: {star: 0 for star in range(1, 6)})
    reviews: list[GymFeedbackReview] = Field(default_factory=list)
