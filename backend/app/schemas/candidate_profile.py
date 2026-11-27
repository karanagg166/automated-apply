"""Bounded, user-supplied career facts and separately stored search preferences."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StrictBool,
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


class CompensationFact(ProfileSchema):
    amount: Decimal = Field(
        ge=0,
        le=Decimal(1000000000000),
        max_digits=15,
        decimal_places=2,
        allow_inf_nan=False,
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: Literal["hour", "month", "year"]
    kind: Literal["ctc", "base_salary", "total_compensation"]


class CountryAuthorization(ProfileSchema):
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    country_name: ShortText
    authorized_to_work: StrictBool
    requires_sponsorship_now_or_future: StrictBool | None = None


class ResumeFileSpec(ProfileSchema):
    """Phase 6A multi-resume picker entry: a local PDF plus optional matching keywords."""

    path: Annotated[str, Field(min_length=1, max_length=500)]
    keywords: StringList = Field(default_factory=list)
    primary: StrictBool = False


LocalPath = Annotated[str, Field(min_length=1, max_length=500)]
BoardToken = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
PortalKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")]


class PortalRuleOverride(ProfileSchema):
    """Python v2 portal rules kept in preferences JSONB (no portal_rules column needed)."""

    allow_unknown_posting_age: StrictBool | None = None


DisclosureText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class ScreeningDisclosures(ProfileSchema):
    """Owner-declared answers for EEO / consent / NDA screening questions.

    These questions are otherwise always sent to the human. Only explicitly stored
    values are used to answer them (tier 0, never cached, never sent to an LLM).
    """

    gender: DisclosureText | None = None
    ethnicity: DisclosureText | None = None
    veteran_status: DisclosureText | None = None
    disability_status: DisclosureText | None = None
    pronouns: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ] | None = None
    date_of_birth: date | None = None
    citizenship: DisclosureText | None = None
    has_valid_passport: StrictBool | None = None
    consent_background_check: StrictBool | None = None
    consent_data_processing: StrictBool | None = None
    agree_terms: StrictBool | None = None
    nda_auto_sign: StrictBool | None = None
    nda_signature_name: DisclosureText | None = None
    currently_employed: StrictBool | None = None

    @model_validator(mode="after")
    def plausible_values(self):
        if self.date_of_birth and not date(1900, 1, 1) <= self.date_of_birth <= date.today():
            raise ValueError("date_of_birth must be between 1900-01-01 and today")
        if self.nda_auto_sign and not self.nda_signature_name:
            raise ValueError("nda_auto_sign requires nda_signature_name")
        return self


class JobSearchPreferences(ProfileSchema):
    current_compensation: CompensationFact | None = None
    expected_compensation: CompensationFact | None = None
    availability_date: date | None = None
    current_location: ShortText | None = None
    # Phase 8 canonical screening facts (Greenhouse Country, Lever Current company / English).
    country: ShortText | None = None
    current_company: ShortText | None = None
    current_title: ShortText | None = None
    english_proficiency: ShortText | None = None
    open_to_relocation: StrictBool | None = None
    relocation_locations: StringList = Field(default_factory=list)
    work_authorizations: list[CountryAuthorization] = Field(
        default_factory=list, max_length=20
    )
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
    # Python v2 rules engine + deterministic screening facts (AGENTS.md §5A).
    # CTC values are INR lakhs per annum (LPA); skill_years maps a skill to years.
    target_roles: StringList = Field(default_factory=list)
    keywords_required: StringList = Field(default_factory=list)
    keywords_excluded: StringList = Field(default_factory=list)
    tech_stack: StringList = Field(default_factory=list)
    company_blacklist: StringList = Field(default_factory=list)
    remote_policy: Literal["any", "remote_only", "hybrid_ok", "onsite_ok"] | None = None
    skill_match_mode: Literal["any", "all"] | None = None
    min_match_score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    current_ctc: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    expected_ctc: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    min_ctc: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    total_experience_years: float | None = Field(default=None, ge=0, le=60, allow_inf_nan=False)
    willing_to_relocate: StrictBool | None = None
    skill_years: dict[ShortText, Annotated[float, Field(ge=0, le=60, allow_inf_nan=False)]] = Field(
        default_factory=dict, max_length=100
    )
    # Phase 6A: local resume PDFs per variant and public ATS board tokens (no secrets).
    resume_files: dict[ShortText, ResumeFileSpec | LocalPath] = Field(default_factory=dict, max_length=10)
    greenhouse_boards: dict[BoardToken, ShortText | None] = Field(default_factory=dict, max_length=25)
    lever_boards: dict[BoardToken, ShortText | None] = Field(default_factory=dict, max_length=25)
    ashby_boards: dict[BoardToken, ShortText | None] = Field(default_factory=dict, max_length=25)
    smartrecruiters_boards: dict[BoardToken, ShortText | None] = Field(default_factory=dict, max_length=25)
    # Phase 8: per-portal rule overrides edited from /autopilot (portal rules PATCH).
    portal_rule_overrides: dict[PortalKey, PortalRuleOverride] = Field(default_factory=dict, max_length=20)
    # Phase 9B: hard experience ceiling for the filter, profile headline, internship facts and
    # early-bird notifications.
    max_required_experience_years: float | None = Field(default=None, ge=0, le=30, allow_inf_nan=False)
    headline: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)] | None = None
    internship_months: int | None = Field(default=None, ge=0, le=60)
    graduation_month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] | None = None
    open_to_internships: StrictBool | None = None
    notify_early_bird: StrictBool | None = None
    # Phase 9D: per-portal profile-sync switches, e.g. {"naukri": {"live": true}} (default: dry-run only).
    profile_sync: dict[PortalKey, dict[ShortText, StrictBool]] | None = None
    # Owner-declared EEO / consent / NDA answers (answers/disclosures.py); never derived.
    screening_disclosures: ScreeningDisclosures | None = None

    @model_validator(mode="after")
    def unique_authorization_countries(self):
        codes = [row.country_code for row in self.work_authorizations]
        if len(codes) != len(set(codes)):
            raise ValueError("Work authorization countries must be unique")
        return self


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
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
