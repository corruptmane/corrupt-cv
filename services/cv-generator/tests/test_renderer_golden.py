"""Golden render tests: canned fixture CVs through the REAL template."""

from pathlib import Path

import pytest
from cv_generator.renderer import Renderer
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
from cv_shared.typst_json import cv_to_typst_json
from pydantic import HttpUrl

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "cv.typ"


@pytest.fixture(scope="module")
def renderer() -> Renderer:
    return Renderer(TEMPLATE_PATH)


def fixture_cv(*, current_role: bool) -> CV:
    return CV(
        personal_info=PersonalInfo(
            name="Jane Doe",
            email="jane.doe@example.com",
            phone="+380 67 000 1122",
            location_city="Lviv",
            location_country="Ukraine",
            links=[Link(label="GitHub", url=HttpUrl("https://github.com/janedoe"))],
        ),
        summary="Backend engineer with six years of experience in event-driven systems.",
        experience=[
            Experience(
                company="Acme Corp",
                position="Senior Backend Engineer",
                start_date="2021-01",
                end_date=None if current_role else "2024-06",
                location="Lviv, Ukraine",
                description="Core platform team.",
                highlights=[
                    "Cut p99 API latency from 800ms to 90ms.",
                    "Led migration of 15 services to Kubernetes.",
                ],
            ),
        ],
        education=[
            Education(
                institution="Lviv Polytechnic",
                degree="MSc",
                field="Software Engineering",
                start_date="2013",
                end_date="2018",
                gpa=3.8,
                highlights=["Graduated with honours."],
            ),
        ],
        skills=[
            Skill(category="Languages", items=["Python", "Go"]),
            Skill(category="Infrastructure", items=["Kubernetes", "NATS", "PostgreSQL"]),
        ],
        projects=[
            Project(
                name="cv-pipeline",
                description="Event-driven CV generation pipeline.",
                url=HttpUrl("https://github.com/janedoe/cv-pipeline"),
                technologies=["Python", "Typst"],
            ),
        ],
        languages=[Language(name="English", proficiency=LanguageProficiency.FLUENT)],
    )


def test_golden_render_produces_pdf(renderer: Renderer) -> None:
    pdf = renderer.render(cv_to_typst_json(fixture_cv(current_role=False)))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 10 * 1024


def test_open_ended_experience_renders_as_present(renderer: Renderer) -> None:
    cv = fixture_cv(current_role=True)
    cv_json = cv_to_typst_json(cv)
    assert '"Present"' in cv_json  # end_date=None normalized before it hits the template
    pdf = renderer.render(cv_json)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 10 * 1024
