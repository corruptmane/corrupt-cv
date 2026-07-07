"""The real Agent run against the fake FunctionModel: valid CV, no network."""

from ai_processor.agent import generate_cv
from ai_processor.fake import build_fake_model
from cv_shared.models import CV
from cvgen.cv.v1 import cv_pb2


def _personal_info() -> cv_pb2.PersonalInfo:
    return cv_pb2.PersonalInfo(
        name="Jane Doe",
        email="jane.doe@example.com",
        phone="+380 67 000 1122",
        location_city="Lviv",
        location_country="Ukraine",
        links=[cv_pb2.Link(label="GitHub", url="https://github.com/janedoe")],
    )


async def test_fake_model_produces_valid_cv_with_personal_info_override() -> None:
    cv = await generate_cv(
        build_fake_model(),
        personal_info=_personal_info(),
        career_text="Six years of backend work.",
        job_description="Platform engineer role.",
    )

    assert isinstance(cv, CV)
    # The canned CV carries different contact data; the request must win.
    assert cv.personal_info.name == "Jane Doe"
    assert str(cv.personal_info.email) == "jane.doe@example.com"
    assert cv.personal_info.phone == "+380 67 000 1122"
    assert cv.personal_info.links[0].label == "GitHub"
    # The professional content comes from the model.
    assert cv.summary
    assert cv.experience
    assert cv.skills
