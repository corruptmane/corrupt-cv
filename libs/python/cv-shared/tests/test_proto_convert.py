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
from cv_shared.proto_convert import cv_from_proto, cv_to_proto, personal_info_from_proto, personal_info_to_proto
from pydantic import HttpUrl

FULL_CV = CV(
    personal_info=PersonalInfo(
        name="Jane Doe",
        email="jane@example.com",
        phone="+380 00 000 0000",
        location_city="Kyiv",
        location_country="Ukraine",
        links=[Link(label="GitHub", url=HttpUrl("https://github.com/janedoe"))],
    ),
    summary="Backend engineer moving to platform engineering.",
    experience=[
        Experience(
            company="Acme",
            position="Senior Backend Engineer",
            start_date="2021-03",
            end_date=None,
            location="Remote",
            description="Built the things.",
            highlights=["Shipped X", "Scaled Y"],
        ),
        Experience(
            company="Beta",
            position="Backend Engineer",
            start_date="2018-01",
            end_date="2021-02",
            location="Kyiv, Ukraine",
            description="Maintained the things.",
        ),
    ],
    education=[
        Education(
            institution="KPI",
            degree="BSc",
            field="Computer Science",
            start_date="2014",
            end_date="2018",
            gpa=3.7,
            highlights=["Thesis on queues"],
        )
    ],
    skills=[Skill(category="Languages", items=["Go", "Python"])],
    projects=[
        Project(
            name="cvgen",
            description="This project.",
            url=HttpUrl("https://github.com/corruptmane/cv"),
            technologies=["Go", "Python", "NATS"],
        ),
        Project(name="sideproj", description="No URL project."),
    ],
    languages=[
        Language(name="Ukrainian", proficiency=LanguageProficiency.NATIVE),
        Language(name="English", proficiency=LanguageProficiency.FLUENT),
    ],
)


def test_cv_round_trip() -> None:
    assert cv_from_proto(cv_to_proto(FULL_CV)) == FULL_CV


def test_personal_info_round_trip_without_phone() -> None:
    info = FULL_CV.personal_info.model_copy(update={"phone": None})
    pb = personal_info_to_proto(info)
    assert not pb.HasField("phone")
    assert personal_info_from_proto(pb) == info


def test_optional_fields_survive_round_trip() -> None:
    pb = cv_to_proto(FULL_CV)
    assert not pb.experience[0].HasField("end_date")
    assert pb.experience[1].end_date == "2021-02"
    assert not pb.projects[1].HasField("url")
    restored = cv_from_proto(pb)
    assert restored.experience[0].end_date is None
    assert restored.projects[1].url is None
