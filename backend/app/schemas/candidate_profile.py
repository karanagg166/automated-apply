"""Bounded, user-supplied career facts and separately stored search preferences."""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    create_model,
    field_validator,
    model_validator,
)

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
LongText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
WebURL = Annotated[HttpUrl, Field(max_length=2048)]
StringList = Annotated[list[ShortText], Field(max_length=100)]


class ProfileSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_strings(cls, value):
        if isinstance(value, dict):
            return {
                key: " ".join(item.split()) if isinstance(item, str) else item
                for key, item in value.items()
            }
        return value

    @field_validator("*", mode="after")
    @classmethod
    def normalize_lists(cls, value):
        if isinstance(value, HttpUrl) and (
            value.username is not None or value.password is not None
        ):
            raise ValueError("URLs must not contain credentials")
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            result, seen = [], set()
            for item in value:
                cleaned = " ".join(item.split())
                if not cleaned:
                    raise ValueError("List entries must not be blank")
                if cleaned.casefold() not in seen:
                    result.append(cleaned)
                    seen.add(cleaned.casefold())
            return result
        return value

    @model_validator(mode="after")
    def bound_payload(self):
        if (
            len(
                self.model_dump_json(
                    exclude={
                        "id",
                        "singleton_key",
                        "version",
                        "created_at",
                        "updated_at",
                    }
                ).encode("utf-8")
            )
            > 65536
        ):
            raise ValueError("Profile payload must not exceed 64 KiB")
        return self


class ProfessionalExperience(ProfileSchema):
    company: ShortText
    role: ShortText
    start_date: date | None = None
    end_date: date | None = None
    highlight: LongText | None = None

    @model_validator(mode="after")
    def chronological_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class EducationRecord(ProfileSchema):
    institution: ShortText
    qualification: ShortText
    field_of_study: ShortText | None = None
    graduation_year: int | None = Field(default=None, ge=1900, le=2200)


class VerifiedProject(ProfileSchema):
    name: ShortText
    description: LongText | None = None
    url: WebURL | None = None
    technologies: StringList = Field(default_factory=list)
    purpose: LongText | None = None
    contribution: LongText | None = None
    implementation_details: LongText | None = None
    engineering_challenges: LongText | None = None
    solutions: LongText | None = None
    measurable_results: LongText | None = None
    achievements: Annotated[list[LongText], Field(max_length=20)] = Field(
        default_factory=list
    )


class Certification(ProfileSchema):
    name: ShortText
    issuer: ShortText | None = None
    issued_on: date | None = None
    credential_url: WebURL | None = None


class JobSearchPreferences(ProfileSchema):
    target_titles: StringList = Field(default_factory=list)
    technology_stacks: StringList = Field(default_factory=list)
    preferred_locations: StringList = Field(default_factory=list)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] | None = None
    employment_types: list[Literal["full_time", "internship", "contract"]] = Field(
        default_factory=list, max_length=3
    )
    target_industries: StringList = Field(default_factory=list)
    company_stages: StringList = Field(default_factory=list)
    minimum_salary: float | None = Field(
        default=None, ge=0, le=1e12, allow_inf_nan=False
    )
    salary_currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = (
        None
    )
    salary_period: Literal["hour", "day", "week", "month", "year"] | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    work_authorization: ShortText | None = None
    excluded_titles: StringList = Field(default_factory=list)
    excluded_companies: StringList = Field(default_factory=list)
    excluded_keywords: StringList = Field(default_factory=list)
    prioritize_startups: bool | None = None


class CandidateProfileCreate(ProfileSchema):
    full_name: ShortText
    email: Annotated[EmailStr, Field(max_length=254)]
    phone: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = None
    linkedin_url: WebURL | None = None
    github_url: WebURL | None = None
    portfolio_url: WebURL | None = None
    personal_website: WebURL | None = None
    verified_experience_years: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    verified_skills: StringList = Field(default_factory=list)
    verified_roles: list[ProfessionalExperience] = Field(
        default_factory=list, max_length=50
    )
    education: list[EducationRecord] = Field(default_factory=list, max_length=30)
    projects: list[VerifiedProject] = Field(default_factory=list, max_length=50)
    certifications: list[Certification] = Field(default_factory=list, max_length=50)
    summary: LongText | None = None
    preferences: JobSearchPreferences = Field(default_factory=JobSearchPreferences)


# Derive partial fields from the complete schemas to keep their constraints identical.
# Defaults of None express omission only; supplied null still follows the original type.
def partial_schema(name, complete):
    return create_model(
        name,
        __base__=ProfileSchema,
        **{
            key: (field.rebuild_annotation(), None)
            for key, field in complete.model_fields.items()
        },
    )


JobSearchPreferencesUpdate = partial_schema(
    "JobSearchPreferencesUpdate", JobSearchPreferences
)
_ProfileUpdate = partial_schema("_ProfileUpdate", CandidateProfileCreate)


class CandidateProfileUpdate(_ProfileUpdate):
    preferences: JobSearchPreferencesUpdate = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        return self


class CandidateProfileRead(CandidateProfileCreate):
    id: UUID
    singleton_key: Literal["primary"]
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamps(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
