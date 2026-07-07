import json

from cv_shared.typst_json import PRESENT, cv_to_typst_json

from .test_proto_convert import FULL_CV


def test_all_keys_present_with_nulls() -> None:
    doc = json.loads(cv_to_typst_json(FULL_CV))
    # The template dereferences keys directly; optional fields must exist as null.
    info = doc["personal_info"]
    assert set(info) == {"name", "email", "phone", "location_city", "location_country", "links"}
    assert doc["projects"][1]["url"] is None


def test_open_ended_end_date_normalized_to_present() -> None:
    doc = json.loads(cv_to_typst_json(FULL_CV))
    assert doc["experience"][0]["end_date"] == PRESENT
    assert doc["experience"][1]["end_date"] == "2021-02"


def test_proficiency_serializes_as_enum_name() -> None:
    doc = json.loads(cv_to_typst_json(FULL_CV))
    # Template renders lower(proficiency); values must be plain strings.
    assert doc["languages"][0]["proficiency"] == "NATIVE"
