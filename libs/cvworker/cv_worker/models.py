"""Canonical Pydantic CV models — the AI extraction schema. Kept 1:1 with proto
`cv.v1.CV` (see mapping.py).

NOTE: not `strict=True`. These are validated against *LLM-generated* JSON, where
enum values arrive as strings ("NATIVE") and numbers may need coercion; strict
mode rejects those and makes live extraction brittle (see ADR 0006). Coercion is
the right mode for this boundary."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


class Link(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str
    url: HttpUrl


class PersonalInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    email: EmailStr
    phone: str | None = None
    location_city: str
    location_country: str
    links: list[Link] = []


class Experience(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    company: str
    position: str
    start_date: str
    end_date: str | None = None
    location: str
    description: str
    highlights: list[str] = []


class Education(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    institution: str
    degree: str
    field: str
    start_date: str
    end_date: str
    gpa: float | None = None
    highlights: list[str] = []


class Skill(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    items: list[str]


class Project(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    url: HttpUrl | None = None
    technologies: list[str] = []


class LanguageProficiency(str, Enum):  # noqa: UP042 - kept 1:1 with the source schema
    NATIVE = "NATIVE"
    FLUENT = "FLUENT"
    PROFESSIONAL = "PROFESSIONAL"
    INTERMEDIATE = "INTERMEDIATE"
    BASIC = "BASIC"


class Language(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    proficiency: LanguageProficiency


class CVContent(BaseModel):
    """The AI-generated portion of a CV. Deliberately excludes contact info:
    name/email/phone/location/links are authoritative from the form, are NOT sent
    to the model, and are assembled in by the processor (see mapping.content_to_proto).
    Keeping them out of the schema saves tokens and removes any chance of the model
    inventing a contact block."""

    model_config = ConfigDict(populate_by_name=True)

    summary: str
    experience: list[Experience]
    education: list[Education]
    skills: list[Skill]
    projects: list[Project] = []
    languages: list[Language] = []


class CV(CVContent):
    """Full CV = the user's contact block + the AI content (the typst input shape)."""

    personal_info: PersonalInfo
