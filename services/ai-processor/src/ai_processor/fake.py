"""Deterministic fake model for PROVIDER_FAKE: returns a canned CV without any LLM call."""

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
from pydantic import HttpUrl
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def canned_cv() -> CV:
    return CV(
        personal_info=PersonalInfo(
            name="Alex Petrenko",
            email="alex.petrenko@example.com",
            phone="+380 44 123 4567",
            location_city="Kyiv",
            location_country="Ukraine",
            links=[
                Link(label="GitHub", url=HttpUrl("https://github.com/apetrenko")),
                Link(label="LinkedIn", url=HttpUrl("https://linkedin.com/in/apetrenko")),
            ],
        ),
        summary=(
            "Backend engineer moving into platform work: six years building event-driven "
            "Python and Go services, now focused on developer platforms, delivery tooling, "
            "and running reliable infrastructure on Kubernetes."
        ),
        experience=[
            Experience(
                company="Streamline Analytics",
                position="Senior Backend Engineer",
                start_date="2022-03",
                end_date=None,
                location="Kyiv, Ukraine (remote)",
                description="Ingestion platform team for a real-time analytics product.",
                highlights=[
                    "Designed a NATS JetStream event pipeline processing 40M events/day with exactly-once semantics.",
                    "Cut p99 ingestion latency from 900ms to 120ms by re-architecting the hot path in Go.",
                    "Introduced Kubernetes-based preview environments, reducing integration bug escapes by 35%.",
                ],
            ),
            Experience(
                company="Portside Software",
                position="Backend Engineer",
                start_date="2019-06",
                end_date="2022-02",
                location="Kyiv, Ukraine",
                description="Logistics SaaS serving freight forwarders across Europe.",
                highlights=[
                    "Built and operated 12 Python microservices with PostgreSQL and Redis.",
                    "Automated CI/CD with GitLab pipelines, shrinking release cycles from weekly to daily.",
                ],
            ),
        ],
        education=[
            Education(
                institution="Kyiv Polytechnic Institute",
                degree="BSc",
                field="Computer Science",
                start_date="2015",
                end_date="2019",
                gpa=None,
                highlights=[],
            ),
        ],
        skills=[
            Skill(category="Languages", items=["Python", "Go", "SQL", "Bash"]),
            Skill(category="Platform", items=["Kubernetes", "Docker", "Terraform", "GitLab CI", "ArgoCD"]),
            Skill(category="Data & Messaging", items=["PostgreSQL", "NATS", "Kafka", "Redis"]),
            Skill(category="Observability", items=["OpenTelemetry", "Prometheus", "Grafana"]),
        ],
        projects=[
            Project(
                name="kube-preview",
                description="CLI that spins up ephemeral Kubernetes preview environments from a compose file.",
                url=HttpUrl("https://github.com/apetrenko/kube-preview"),
                technologies=["Go", "Kubernetes", "Helm"],
            ),
        ],
        languages=[
            Language(name="Ukrainian", proficiency=LanguageProficiency.NATIVE),
            Language(name="English", proficiency=LanguageProficiency.FLUENT),
        ],
    )


def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    output_tool = info.output_tools[0]
    # JSON-string args so the CV validates in JSON mode: the shared models are
    # strict, and python-mode validation rejects enum values given as strings.
    return ModelResponse(parts=[ToolCallPart(tool_name=output_tool.name, args=canned_cv().model_dump_json())])


def build_fake_model() -> FunctionModel:
    return FunctionModel(_respond, model_name="fake-cv-model")
