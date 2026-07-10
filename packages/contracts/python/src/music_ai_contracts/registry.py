from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyUrl, AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from music_ai_contracts.models import ContractModel, Sha256


class ModelTask(StrEnum):
    SOURCE_SEPARATION = "source_separation"
    F0 = "f0"
    ALIGNMENT = "alignment"
    VAD = "vad"
    QUALITY_GATE = "quality_gate"


class TrainingDataReview(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ModelRecord(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"commercial_use_approved": {"const": True}},
                        "required": ["commercial_use_approved"],
                    },
                    "then": {"properties": {"training_data_review": {"const": "approved"}}},
                }
            ]
        },
    )

    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]+$", min_length=2, max_length=128),
    ]
    task: ModelTask
    artifact_sha256: Sha256
    source_url: AnyUrl
    code_license_spdx: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    weight_license_spdx: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    training_data_review: TrainingDataReview
    commercial_use_approved: bool
    approved_by: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    approved_at: AwareDatetime
    constraints: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_commercial_gate(self) -> ModelRecord:
        if (
            self.commercial_use_approved
            and self.training_data_review != TrainingDataReview.APPROVED
        ):
            raise ValueError("commercial models require approved training data review")
        return self


class ModelRegistryV1(ContractModel):
    schema_version: Literal["model-registry.v1"]
    models: list[ModelRecord] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def validate_unique_model_ids(self) -> ModelRegistryV1:
        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("model_id values must be unique")
        return self


def load_registry(path: Path) -> ModelRegistryV1:
    return ModelRegistryV1.model_validate_json(path.read_text(encoding="utf-8"))


def schema_text() -> str:
    schema = ModelRegistryV1.model_json_schema(mode="validation")
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or verify the model registry schema")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(schema_text(), encoding="utf-8")
    elif args.check and args.check.read_text(encoding="utf-8") != schema_text():
        raise SystemExit(f"model registry schema is stale: {args.check}")


if __name__ == "__main__":
    main()
