"""Pydantic mirror of the cvgen.cv.v1 protobuf contract.

Used as the PydanticAI structured-output type in ai-processor and as the
canonical JSON producer for the Typst template in cv-generator. The wire
format between services is protobuf; see proto_convert for the mapping.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


class Link(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    label: str
    url: HttpUrl


class PersonalInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    name: str
    email: EmailStr
    phone: str | None = None
    location_city: str
    location_country: str
    links: list[Link] = []


class Experience(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    company: str
    position: str
    start_date: str
    end_date: str | None = None
    location: str
    description: str
    highlights: list[str] = []


class Education(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    institution: str
    degree: str
    field: str
    start_date: str
    end_date: str
    gpa: float | None = None
    highlights: list[str] = []


class Skill(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    category: str
    items: list[str]


class Project(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    name: str
    description: str
    url: HttpUrl | None = None
    technologies: list[str] = []


class LanguageProficiency(StrEnum):
    NATIVE = "NATIVE"
    FLUENT = "FLUENT"
    PROFESSIONAL = "PROFESSIONAL"
    INTERMEDIATE = "INTERMEDIATE"
    BASIC = "BASIC"


class Language(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    name: str
    proficiency: LanguageProficiency


class CV(BaseModel):
    model_config = ConfigDict(populate_by_name=True, strict=True)

    personal_info: PersonalInfo
    summary: str
    experience: list[Experience]
    education: list[Education]
    skills: list[Skill]
    projects: list[Project] = []
    languages: list[Language] = []
