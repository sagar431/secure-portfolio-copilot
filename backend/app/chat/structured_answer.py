from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class AnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["supported", "insufficient_evidence"]
    claims: list[ClaimSchema] = Field(max_length=8)
    limitations: list[str] = Field(max_length=5)


ANSWER_SCHEMA = AnswerSchema.model_json_schema(mode="validation")
