"""setup_logging validation: an invalid LOG_LEVEL must fail loudly with the allowed values."""

import pytest
from cv_shared.logging import setup_logging


def test_invalid_level_raises_friendly_error() -> None:
    with pytest.raises(ValueError, match=r"invalid LOG_LEVEL 'BOGUS'") as excinfo:
        setup_logging("BOGUS")
    message = str(excinfo.value)
    for allowed in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert allowed in message


def test_valid_level_is_case_insensitive() -> None:
    setup_logging("warning")
    setup_logging("INFO")
