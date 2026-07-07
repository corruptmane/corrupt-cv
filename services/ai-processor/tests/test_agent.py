from ai_processor.agent import generate_cv
from cv.v1 import generation_pb2 as g
from cv_worker import mapping


def _request() -> g.GenerationRequest:
    req = g.GenerationRequest(
        job_id="job-1",
        experience_text="10 years building Go backends and Kubernetes platforms.",
        job_description="Platform engineer: k8s, CI/CD, observability.",
        provider=g.PROVIDER_TEST,
    )
    req.contacts.name = "Ada Lovelace"
    req.contacts.email = "ada@example.com"
    req.contacts.location_city = "London"
    req.contacts.location_country = "UK"
    req.contacts.links.add(label="GitHub", url="https://github.com/ada")
    return req


async def test_test_provider_produces_content() -> None:
    content = await generate_cv(_request(), api_key="", ollama_base_url="http://x")
    # The AI content has no contact block — that's assembled from the form.
    assert not hasattr(content, "personal_info")
    assert content.summary
    assert content.experience and content.education and content.skills


async def test_assemble_content_plus_contacts() -> None:
    req = _request()
    content = await generate_cv(req, api_key="", ollama_base_url="http://x")

    proto = mapping.content_to_proto(content, req.contacts)
    # Contacts come from the form...
    assert proto.personal_info.name == "Ada Lovelace"
    assert proto.personal_info.links[0].url == "https://github.com/ada"
    # ...content comes from the AI output.
    assert proto.summary and proto.experience

    data = mapping.proto_to_dict(proto)
    assert data["personal_info"]["name"] == "Ada Lovelace"
    assert data["languages"][0]["proficiency"] == "FLUENT"
