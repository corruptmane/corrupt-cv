"""Converters between the pydantic CV models and cvgen.cv.v1 protobuf messages."""

from cvgen.cv.v1 import cv_pb2
from pydantic import HttpUrl, ValidationError

from cv_shared.models import (
    CV,
    Education,
    Experience,
    Language,
    LanguageProficiency,
    Link,
    PersonalInfo,
    Project,
    Skill,
)


class ContractViolation(ValueError):
    """A proto payload violates the CV contract; the message names the field, never the value."""


_PROFICIENCY_TO_PROTO: dict[LanguageProficiency, cv_pb2.LanguageProficiency.ValueType] = {
    LanguageProficiency.NATIVE: cv_pb2.LANGUAGE_PROFICIENCY_NATIVE,
    LanguageProficiency.FLUENT: cv_pb2.LANGUAGE_PROFICIENCY_FLUENT,
    LanguageProficiency.PROFESSIONAL: cv_pb2.LANGUAGE_PROFICIENCY_PROFESSIONAL,
    LanguageProficiency.INTERMEDIATE: cv_pb2.LANGUAGE_PROFICIENCY_INTERMEDIATE,
    LanguageProficiency.BASIC: cv_pb2.LANGUAGE_PROFICIENCY_BASIC,
}
_PROFICIENCY_FROM_PROTO = {v: k for k, v in _PROFICIENCY_TO_PROTO.items()}


def failure_detail(exc: Exception) -> str:
    """Safe terminal-failure detail for JobFailed copy: exception class plus field context only.

    Never includes payload contents (PII discipline) — pydantic errors are reduced to their
    loc/type codes, and only ContractViolation messages (payload-free by contract) pass through.
    """
    if isinstance(exc, ValidationError):
        locs = "; ".join(
            ".".join(str(part) for part in error["loc"]) or "<root>" for error in exc.errors(include_url=False)
        )
        return f"{type(exc).__name__}: {locs}"
    if isinstance(exc, ContractViolation):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


def _http_url(value: str, field: str) -> HttpUrl:
    try:
        return HttpUrl(value)
    except ValidationError as exc:
        reasons = ", ".join(error["type"] for error in exc.errors(include_url=False))
        raise ContractViolation(f"{field}: invalid URL ({reasons})") from None


def _proficiency_from_proto(value: cv_pb2.LanguageProficiency.ValueType) -> LanguageProficiency:
    # UNSPECIFIED (0) and any out-of-range id are invalid input, not a silent default.
    try:
        return _PROFICIENCY_FROM_PROTO[value]
    except KeyError:
        try:
            name = cv_pb2.LanguageProficiency.Name(value)
        except ValueError:
            name = str(value)
        raise ContractViolation(f"languages[].proficiency: unsupported value {name}") from None


def personal_info_to_proto(info: PersonalInfo) -> cv_pb2.PersonalInfo:
    pb = cv_pb2.PersonalInfo(
        name=info.name,
        email=str(info.email),
        location_city=info.location_city,
        location_country=info.location_country,
        links=[cv_pb2.Link(label=link.label, url=str(link.url)) for link in info.links],
    )
    if info.phone is not None:
        pb.phone = info.phone
    return pb


def personal_info_from_proto(pb: cv_pb2.PersonalInfo) -> PersonalInfo:
    return PersonalInfo(
        name=pb.name,
        email=pb.email,
        phone=pb.phone if pb.HasField("phone") else None,
        location_city=pb.location_city,
        location_country=pb.location_country,
        links=[Link(label=link.label, url=_http_url(link.url, "personal_info.links[].url")) for link in pb.links],
    )


def cv_to_proto(cv: CV) -> cv_pb2.CV:
    pb = cv_pb2.CV(
        personal_info=personal_info_to_proto(cv.personal_info),
        summary=cv.summary,
        skills=[cv_pb2.Skill(category=s.category, items=s.items) for s in cv.skills],
        languages=[
            cv_pb2.Language(name=lang.name, proficiency=_PROFICIENCY_TO_PROTO[lang.proficiency])
            for lang in cv.languages
        ],
    )
    for exp in cv.experience:
        exp_pb = pb.experience.add(
            company=exp.company,
            position=exp.position,
            start_date=exp.start_date,
            location=exp.location,
            description=exp.description,
            highlights=exp.highlights,
        )
        if exp.end_date is not None:
            exp_pb.end_date = exp.end_date
    for edu in cv.education:
        edu_pb = pb.education.add(
            institution=edu.institution,
            degree=edu.degree,
            field=edu.field,
            start_date=edu.start_date,
            end_date=edu.end_date,
            highlights=edu.highlights,
        )
        if edu.gpa is not None:
            edu_pb.gpa = edu.gpa
    for proj in cv.projects:
        proj_pb = pb.projects.add(
            name=proj.name,
            description=proj.description,
            technologies=proj.technologies,
        )
        if proj.url is not None:
            proj_pb.url = str(proj.url)
    return pb


def cv_from_proto(pb: cv_pb2.CV) -> CV:
    return CV(
        personal_info=personal_info_from_proto(pb.personal_info),
        summary=pb.summary,
        experience=[
            Experience(
                company=e.company,
                position=e.position,
                start_date=e.start_date,
                end_date=e.end_date if e.HasField("end_date") else None,
                location=e.location,
                description=e.description,
                highlights=list(e.highlights),
            )
            for e in pb.experience
        ],
        education=[
            Education(
                institution=e.institution,
                degree=e.degree,
                field=e.field,
                start_date=e.start_date,
                end_date=e.end_date,
                gpa=e.gpa if e.HasField("gpa") else None,
                highlights=list(e.highlights),
            )
            for e in pb.education
        ],
        skills=[Skill(category=s.category, items=list(s.items)) for s in pb.skills],
        projects=[
            Project(
                name=p.name,
                description=p.description,
                url=_http_url(p.url, "projects[].url") if p.HasField("url") else None,
                technologies=list(p.technologies),
            )
            for p in pb.projects
        ],
        languages=[
            Language(name=lang.name, proficiency=_proficiency_from_proto(lang.proficiency)) for lang in pb.languages
        ],
    )
