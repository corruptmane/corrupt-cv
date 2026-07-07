from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Provider(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROVIDER_UNSPECIFIED: _ClassVar[Provider]
    PROVIDER_ANTHROPIC: _ClassVar[Provider]
    PROVIDER_OPENAI: _ClassVar[Provider]
    PROVIDER_GOOGLE: _ClassVar[Provider]
    PROVIDER_FAKE: _ClassVar[Provider]
PROVIDER_UNSPECIFIED: Provider
PROVIDER_ANTHROPIC: Provider
PROVIDER_OPENAI: Provider
PROVIDER_GOOGLE: Provider
PROVIDER_FAKE: Provider

class ModelCatalogEntry(_message.Message):
    __slots__ = ("key", "provider", "model_id", "display_name", "description")
    KEY_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    key: str
    provider: Provider
    model_id: str
    display_name: str
    description: str
    def __init__(self, key: _Optional[str] = ..., provider: _Optional[_Union[Provider, str]] = ..., model_id: _Optional[str] = ..., display_name: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...
