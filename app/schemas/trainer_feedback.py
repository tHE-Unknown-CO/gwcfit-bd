from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


FEEDBACK_OPTIONS = {
    "Knowledgeable and helpful",
    "Motivating and encouraging",
    "Personalized my workouts",
    "Clear communication",
    "Could improve availability",
    "Other",
}


class TrainerFeedbackUpsert(BaseModel):
    rating: int = Field(default=5, ge=1, le=5)
    feedback_option: str | None = Field(default=None, max_length=120)
    feedback_text: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def validate_feedback(self):
        if self.feedback_option is not None and self.feedback_option not in FEEDBACK_OPTIONS:
            raise ValueError("Choose a supported feedback option.")
        if self.feedback_option == "Other" and not (self.feedback_text or "").strip():
            raise ValueError("Custom feedback is required when Other is selected.")
        if self.feedback_option != "Other" and self.feedback_text:
            raise ValueError("Custom feedback is only allowed with Other.")
        return self


class MemberTrainerFeedbackRead(BaseModel):
    id: UUID
    trainer_id: UUID
    review_month: date
    rating: int
    feedback_option: str | None = None
    feedback_text: str | None = None
    created_at: datetime
    updated_at: datetime


class TrainerFeedbackRead(MemberTrainerFeedbackRead):
    member_id: UUID
    member_name: str


class TrainerRatingSummary(BaseModel):
    average_rating: float = 0
    total_reviews: int = 0
    star_distribution: dict[int, int] = Field(default_factory=lambda: {star: 0 for star in range(1, 6)})
    reviews: list[TrainerFeedbackRead] = Field(default_factory=list)
