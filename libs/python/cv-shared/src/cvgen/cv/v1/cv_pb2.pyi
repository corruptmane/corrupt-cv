from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LanguageProficiency(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    LANGUAGE_PROFICIENCY_UNSPECIFIED: _ClassVar[LanguageProficiency]
    LANGUAGE_PROFICIENCY_NATIVE: _ClassVar[LanguageProficiency]
    LANGUAGE_PROFICIENCY_FLUENT: _ClassVar[LanguageProficiency]
    LANGUAGE_PROFICIENCY_PROFESSIONAL: _ClassVar[LanguageProficiency]
    LANGUAGE_PROFICIENCY_INTERMEDIATE: _ClassVar[LanguageProficiency]
    LANGUAGE_PROFICIENCY_BASIC: _ClassVar[LanguageProficiency]
LANGUAGE_PROFICIENCY_UNSPECIFIED: LanguageProficiency
LANGUAGE_PROFICIENCY_NATIVE: LanguageProficiency
LANGUAGE_PROFICIENCY_FLUENT: LanguageProficiency
LANGUAGE_PROFICIENCY_PROFESSIONAL: LanguageProficiency
LANGUAGE_PROFICIENCY_INTERMEDIATE: LanguageProficiency
LANGUAGE_PROFICIENCY_BASIC: LanguageProficiency

class Link(_message.Message):
    __slots__ = ("label", "url")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    label: str
    url: str
    def __init__(self, label: _Optional[str] = ..., url: _Optional[str] = ...) -> None: ...

class PersonalInfo(_message.Message):
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
    links: _containers.RepeatedCompositeFieldContainer[Link]
    def __init__(self, name: _Optional[str] = ..., email: _Optional[str] = ..., phone: _Optional[str] = ..., location_city: _Optional[str] = ..., location_country: _Optional[str] = ..., links: _Optional[_Iterable[_Union[Link, _Mapping]]] = ...) -> None: ...

class Experience(_message.Message):
    __slots__ = ("company", "position", "start_date", "end_date", "location", "description", "highlights")
    COMPANY_FIELD_NUMBER: _ClassVar[int]
    POSITION_FIELD_NUMBER: _ClassVar[int]
    START_DATE_FIELD_NUMBER: _ClassVar[int]
    END_DATE_FIELD_NUMBER: _ClassVar[int]
    LOCATION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    HIGHLIGHTS_FIELD_NUMBER: _ClassVar[int]
    company: str
    position: str
    start_date: str
    end_date: str
    location: str
    description: str
    highlights: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, company: _Optional[str] = ..., position: _Optional[str] = ..., start_date: _Optional[str] = ..., end_date: _Optional[str] = ..., location: _Optional[str] = ..., description: _Optional[str] = ..., highlights: _Optional[_Iterable[str]] = ...) -> None: ...

class Education(_message.Message):
    __slots__ = ("institution", "degree", "field", "start_date", "end_date", "gpa", "highlights")
    INSTITUTION_FIELD_NUMBER: _ClassVar[int]
    DEGREE_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    START_DATE_FIELD_NUMBER: _ClassVar[int]
    END_DATE_FIELD_NUMBER: _ClassVar[int]
    GPA_FIELD_NUMBER: _ClassVar[int]
    HIGHLIGHTS_FIELD_NUMBER: _ClassVar[int]
    institution: str
    degree: str
    field: str
    start_date: str
    end_date: str
    gpa: float
    highlights: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, institution: _Optional[str] = ..., degree: _Optional[str] = ..., field: _Optional[str] = ..., start_date: _Optional[str] = ..., end_date: _Optional[str] = ..., gpa: _Optional[float] = ..., highlights: _Optional[_Iterable[str]] = ...) -> None: ...

class Skill(_message.Message):
    __slots__ = ("category", "items")
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    category: str
    items: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, category: _Optional[str] = ..., items: _Optional[_Iterable[str]] = ...) -> None: ...

class Project(_message.Message):
    __slots__ = ("name", "description", "url", "technologies")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    TECHNOLOGIES_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    url: str
    technologies: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., url: _Optional[str] = ..., technologies: _Optional[_Iterable[str]] = ...) -> None: ...

class Language(_message.Message):
    __slots__ = ("name", "proficiency")
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROFICIENCY_FIELD_NUMBER: _ClassVar[int]
    name: str
    proficiency: LanguageProficiency
    def __init__(self, name: _Optional[str] = ..., proficiency: _Optional[_Union[LanguageProficiency, str]] = ...) -> None: ...

class CV(_message.Message):
    __slots__ = ("personal_info", "summary", "experience", "education", "skills", "projects", "languages")
    PERSONAL_INFO_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    EXPERIENCE_FIELD_NUMBER: _ClassVar[int]
    EDUCATION_FIELD_NUMBER: _ClassVar[int]
    SKILLS_FIELD_NUMBER: _ClassVar[int]
    PROJECTS_FIELD_NUMBER: _ClassVar[int]
    LANGUAGES_FIELD_NUMBER: _ClassVar[int]
    personal_info: PersonalInfo
    summary: str
    experience: _containers.RepeatedCompositeFieldContainer[Experience]
    education: _containers.RepeatedCompositeFieldContainer[Education]
    skills: _containers.RepeatedCompositeFieldContainer[Skill]
    projects: _containers.RepeatedCompositeFieldContainer[Project]
    languages: _containers.RepeatedCompositeFieldContainer[Language]
    def __init__(self, personal_info: _Optional[_Union[PersonalInfo, _Mapping]] = ..., summary: _Optional[str] = ..., experience: _Optional[_Iterable[_Union[Experience, _Mapping]]] = ..., education: _Optional[_Iterable[_Union[Education, _Mapping]]] = ..., skills: _Optional[_Iterable[_Union[Skill, _Mapping]]] = ..., projects: _Optional[_Iterable[_Union[Project, _Mapping]]] = ..., languages: _Optional[_Iterable[_Union[Language, _Mapping]]] = ...) -> None: ...
