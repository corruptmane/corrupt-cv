from cv.v1 import cv_pb2
from cv_generator.render import render_pdf
from cv_worker import mapping


def _sample_proto() -> cv_pb2.CV:
    cv = cv_pb2.CV(summary="Platform engineer focused on developer experience and reliability.")
    pi = cv.personal_info
    pi.name = "Ada Lovelace"
    pi.email = "ada@example.com"
    pi.phone = "+44 20 7946 0000"
    pi.location_city = "London"
    pi.location_country = "UK"
    pi.links.add(label="GitHub", url="https://github.com/ada")

    e = cv.experience.add(
        company="Analytical Engines",
        position="Lead Platform Engineer",
        start_date="2020",
        location="London",
        description="Owned the internal delivery platform.",
    )
    e.highlights.extend(["Cut deploy time by 80%", "Built progressive-delivery CI/CD"])

    ed = cv.education.add(
        institution="University of Cambridge",
        degree="BSc",
        field="Mathematics",
        start_date="2014",
        end_date="2018",
    )
    ed.gpa = 3.9

    cv.skills.add(category="Platform", items=["Kubernetes", "NATS", "OpenTelemetry"])

    p = cv.projects.add(name="cvgen", description="AI-tailored CV generator", url="https://example.com")
    p.technologies.extend(["Go", "Python", "Typst"])

    cv.languages.add(name="English", proficiency=cv_pb2.LANGUAGE_PROFICIENCY_NATIVE)
    return cv


def test_render_produces_pdf() -> None:
    data = mapping.proto_to_dict(_sample_proto())
    pdf = render_pdf(data)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_render_minimal_cv() -> None:
    # Optional fields and repeated sections absent -> template must still compile.
    cv = cv_pb2.CV(summary="")
    pi = cv.personal_info
    pi.name = "Min"
    pi.email = "min@example.com"
    pi.location_city = "X"
    pi.location_country = "Y"
    assert render_pdf(mapping.proto_to_dict(cv))[:5] == b"%PDF-"
