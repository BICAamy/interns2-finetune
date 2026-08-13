"""Common settings for all versioned service contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


SCHEMA_VERSION = "1.0"
SchemaVersion = Literal["1.0"]


class ContractModel(BaseModel):
    """Strict base model used at every service boundary."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )
