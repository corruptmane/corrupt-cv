"""Conversions between the Pydantic CV content (models.py) and proto `cv.v1`.

- content_to_proto: assemble the wire `CV` from the AI-generated content +
  the authoritative form contacts (which the model never sees or produces).
- proto_to_dict: wire message -> a COMPLETE typst-input dict (every field present,
  None for unset optionals, [] for empty repeated) as the cv.typ template expects."""

from typing import Any

from cv.v1 import cv_pb2, generation_pb2

from . import models

_PROF_TO_PROTO = {
    models.LanguageProficiency.NATIVE: cv_pb2.LANGUAGE_PROFICIENCY_NATIVE,
    models.LanguageProficiency.FLUENT: cv_pb2.LANGUAGE_PROFICIENCY_FLUENT,
    models.LanguageProficiency.PROFESSIONAL: cv_pb2.LANGUAGE_PROFICIENCY_PROFESSIONAL,
    models.LanguageProficiency.INTERMEDIATE: cv_pb2.LANGUAGE_PROFICIENCY_INTERMEDIATE,
    models.LanguageProficiency.BASIC: cv_pb2.LANGUAGE_PROFICIENCY_BASIC,
}


def content_to_proto(
    content: models.CVContent, contacts: generation_pb2.Contacts
) -> cv_pb2.CV:
    out = cv_pb2.CV(summary=content.summary)

    # Contact block is authoritative from the form — never model-generated.
    pi = out.personal_info
    pi.name = contacts.name
    pi.email = contacts.email
    if contacts.HasField("phone"):
        pi.phone = contacts.phone
    pi.location_city = contacts.location_city
    pi.location_country = contacts.location_country
    for link in contacts.links:
        pi.links.add(label=link.label, url=link.url)

    for e in content.experience:
        pe = out.experience.add(
            company=e.company,
            position=e.position,
            start_date=e.start_date,
            location=e.location,
            description=e.description,
        )
        if e.end_date is not None:
            pe.end_date = e.end_date
        pe.highlights.extend(e.highlights)

    for ed in content.education:
        ped = out.education.add(
            institution=ed.institution,
            degree=ed.degree,
            field=ed.field,
            start_date=ed.start_date,
            end_date=ed.end_date,
        )
        if ed.gpa is not None:
            ped.gpa = ed.gpa
        ped.highlights.extend(ed.highlights)

    for s in content.skills:
        out.skills.add(category=s.category, items=s.items)

    for pr in content.projects:
        pp = out.projects.add(name=pr.name, description=pr.description)
        if pr.url is not None:
            pp.url = str(pr.url)
        pp.technologies.extend(pr.technologies)

    for lang in content.languages:
        out.languages.add(name=lang.name, proficiency=_PROF_TO_PROTO[lang.proficiency])

    return out


def _proficiency_name(value: int) -> str:
    return cv_pb2.LanguageProficiency.Name(value).removeprefix("LANGUAGE_PROFICIENCY_")


def proto_to_dict(cv: cv_pb2.CV) -> dict[str, Any]:
    pi = cv.personal_info
    return {
        "personal_info": {
            "name": pi.name,
            "email": pi.email,
            "phone": pi.phone if pi.HasField("phone") else None,
            "location_city": pi.location_city,
            "location_country": pi.location_country,
            "links": [{"label": link.label, "url": link.url} for link in pi.links],
        },
        "summary": cv.summary,
        "experience": [
            {
                "company": e.company,
                "position": e.position,
                "start_date": e.start_date,
                "end_date": e.end_date if e.HasField("end_date") else None,
                "location": e.location,
                "description": e.description,
                "highlights": list(e.highlights),
            }
            for e in cv.experience
        ],
        "education": [
            {
                "institution": ed.institution,
                "degree": ed.degree,
                "field": ed.field,
                "start_date": ed.start_date,
                "end_date": ed.end_date,
                "gpa": ed.gpa if ed.HasField("gpa") else None,
                "highlights": list(ed.highlights),
            }
            for ed in cv.education
        ],
        "skills": [{"category": s.category, "items": list(s.items)} for s in cv.skills],
        "projects": [
            {
                "name": p.name,
                "description": p.description,
                "url": p.url if p.HasField("url") else None,
                "technologies": list(p.technologies),
            }
            for p in cv.projects
        ],
        "languages": [
            {"name": lang.name, "proficiency": _proficiency_name(lang.proficiency)}
            for lang in cv.languages
        ],
    }
