import datetime

from cvgen.cv.v1 import cv_pb2 as _cv_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class JobStage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOB_STAGE_UNSPECIFIED: _ClassVar[JobStage]
    JOB_STAGE_PROCESSING: _ClassVar[JobStage]
    JOB_STAGE_RENDERING: _ClassVar[JobStage]
JOB_STAGE_UNSPECIFIED: JobStage
JOB_STAGE_PROCESSING: JobStage
JOB_STAGE_RENDERING: JobStage

class JobRequested(_message.Message):
    __slots__ = ("job_id", "career_text", "job_description", "personal_info", "model_key", "occurred_at")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CAREER_TEXT_FIELD_NUMBER: _ClassVar[int]
    JOB_DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PERSONAL_INFO_FIELD_NUMBER: _ClassVar[int]
    MODEL_KEY_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    career_text: str
    job_description: str
    personal_info: _cv_pb2.PersonalInfo
    model_key: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, job_id: _Optional[str] = ..., career_text: _Optional[str] = ..., job_description: _Optional[str] = ..., personal_info: _Optional[_Union[_cv_pb2.PersonalInfo, _Mapping]] = ..., model_key: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class JobStructured(_message.Message):
    __slots__ = ("job_id", "cv", "occurred_at")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CV_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    cv: _cv_pb2.CV
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, job_id: _Optional[str] = ..., cv: _Optional[_Union[_cv_pb2.CV, _Mapping]] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class JobRendered(_message.Message):
    __slots__ = ("job_id", "pdf_object_key", "occurred_at")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    PDF_OBJECT_KEY_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    pdf_object_key: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, job_id: _Optional[str] = ..., pdf_object_key: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class JobFailed(_message.Message):
    __slots__ = ("job_id", "stage", "error", "occurred_at")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    stage: JobStage
    error: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, job_id: _Optional[str] = ..., stage: _Optional[_Union[JobStage, str]] = ..., error: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
