from cv.v1 import cv_pb2 as _cv_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Provider(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROVIDER_UNSPECIFIED: _ClassVar[Provider]
    PROVIDER_OPENAI: _ClassVar[Provider]
    PROVIDER_ANTHROPIC: _ClassVar[Provider]
    PROVIDER_GEMINI: _ClassVar[Provider]
    PROVIDER_OLLAMA: _ClassVar[Provider]
    PROVIDER_TEST: _ClassVar[Provider]

class Stage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STAGE_UNSPECIFIED: _ClassVar[Stage]
    STAGE_AI: _ClassVar[Stage]
    STAGE_RENDER: _ClassVar[Stage]
PROVIDER_UNSPECIFIED: Provider
PROVIDER_OPENAI: Provider
PROVIDER_ANTHROPIC: Provider
PROVIDER_GEMINI: Provider
PROVIDER_OLLAMA: Provider
PROVIDER_TEST: Provider
STAGE_UNSPECIFIED: Stage
STAGE_AI: Stage
STAGE_RENDER: Stage

class Contacts(_message.Message):
    __slots__ = ("name", "email", "phone", "location_city", "location_country", "links")
    NAME_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    PHONE_FIELD_NUMBER: _ClassVar[int]
    LOCATION_CITY_FIELD_NUMBER: _ClassVar[int]
    LOCATION_COUNTRY_FIELD_NUMBER: _ClassVar[int]
    LINKS_FIELD_NUMBER: _ClassVar[int]
    name: str
    email: str
    phone: str
    location_city: str
    location_country: str
    links: _containers.RepeatedCompositeFieldContainer[_cv_pb2.Link]
    def __init__(self, name: _Optional[str] = ..., email: _Optional[str] = ..., phone: _Optional[str] = ..., location_city: _Optional[str] = ..., location_country: _Optional[str] = ..., links: _Optional[_Iterable[_Union[_cv_pb2.Link, _Mapping]]] = ...) -> None: ...

class GenerationRequest(_message.Message):
    __slots__ = ("job_id", "experience_text", "job_description", "contacts", "provider", "model")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    EXPERIENCE_TEXT_FIELD_NUMBER: _ClassVar[int]
    JOB_DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    CONTACTS_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    experience_text: str
    job_description: str
    contacts: Contacts
    provider: Provider
    model: str
    def __init__(self, job_id: _Optional[str] = ..., experience_text: _Optional[str] = ..., job_description: _Optional[str] = ..., contacts: _Optional[_Union[Contacts, _Mapping]] = ..., provider: _Optional[_Union[Provider, str]] = ..., model: _Optional[str] = ...) -> None: ...

class CVStructured(_message.Message):
    __slots__ = ("job_id", "cv", "provider", "model")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CV_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    cv: _cv_pb2.CV
    provider: Provider
    model: str
    def __init__(self, job_id: _Optional[str] = ..., cv: _Optional[_Union[_cv_pb2.CV, _Mapping]] = ..., provider: _Optional[_Union[Provider, str]] = ..., model: _Optional[str] = ...) -> None: ...

class CVCompleted(_message.Message):
    __slots__ = ("job_id", "object_key", "size_bytes")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    OBJECT_KEY_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    object_key: str
    size_bytes: int
    def __init__(self, job_id: _Optional[str] = ..., object_key: _Optional[str] = ..., size_bytes: _Optional[int] = ...) -> None: ...

class CVFailed(_message.Message):
    __slots__ = ("job_id", "stage", "message")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    stage: Stage
    message: str
    def __init__(self, job_id: _Optional[str] = ..., stage: _Optional[_Union[Stage, str]] = ..., message: _Optional[str] = ...) -> None: ...
