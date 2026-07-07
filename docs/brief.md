/ultraplan let's create a AI-powered CV generator. This would be a display project for my CV, however I am open for it to become a product.
This should be a website/webapp that would either prompt user for their AI API key to access the AI capabilities or would have a paid plan that would allow them to access the AI capabilities.
The flow is - user has either entered their full work experience, education etc. as a text to the input modal or it is saved somewhere. After that user sends the job description, fills out some predefined values like contacts or
something like that.
After that our service serializes the data in some proper way, sends it to AI to get structured response. With that structured response we generate a per-job tailored CV.

Since I was originally a backend engineer and I'm planning to switch to platform engineer - the focus of this project should be on the platform - everything around the codebase: infrastructure, CI/CD, k8s deploy, ADRs, etc.

I think I already described the product side, now I'd like to describe the project side as I see it:

- Golang on the API-gateway
- Either HTMX or React on the front-end side
- Python on the AI processor and CV generator (separate services)
- Kubernetes-focused automatic gradual deployment like canary or blue/green
- CI/CD and ADRs
- Victoria stack for metrics/logs/traces backend, opentelemetry as a wire
- postgresql for DB, valkey for cache (if needed)
- typst for PDF generation
- AI processor is multiprovider, so it should be able to process data through different providers and models.
- NATS (jetstream) for queue/pubsub
- protobuf for contracts between services
- opentofu for infra management
- github actions as a CI/CD
- application parts can be ran locally on macos/linux for development/testing
- OpenDAL as storage interface on python side and aws-sdk v2 with only S3 package on golang side
- native typst templating via `sys_inputs`, no templating engine
- clarification on initial CV structure, I see it like this (it's pydantic now but should be as a protobuf):
```python3
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


class LanguageProficiency(str, Enum):
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
```
- approximate typst template is at @cv.typ
- single repo, each service is in a different directory under `services/` or smth like it.
- especially for python side services there'd be some code shared between both, so we'd need some kind of shared lib for that
- everything protobuf related is in a `proto/` directory, the `buf` files and the protobufs themselves in there with something like a `domain/version/name.proto` structure
- structlog in python
- let's implement both readiness and liveness probes to conform with k8s, and I also think it's acceptable to launch separate servers for the gateway process, one is production, another is operational for metrics/probes
- since multiple services can potentially run nats commands (create streams/consumers etc.) let's stick to single authority in that regard - the gateway is responsible for creating those durable streams/consumers and python side can only subscibe and publish, not create entities
- valkey packages where needed since we target it
- also let's use the opentelemetry instrumentation where possible, not reinvent the wheel
- python 3.13, no `from __future__` nonsense
- we'd also need some kind of dynconfig for model selection. selection should be fixed, maybe searchable by prefix or fuzzy search, don't let user send and model id since we'd have to use it the query with pydanticai. what backend I'm not sure yet - yaml/redis/nats-KV etc.
- multistage builds for less bloat in the images
- migrations should be ran outside of the services, scripts or jobs of some sorts
