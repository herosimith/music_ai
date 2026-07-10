from __future__ import annotations

import argparse
import json
from pathlib import Path

from music_ai_contracts.models import CONTRACT_MODELS


def schemas() -> dict[str, dict[str, object]]:
    return {
        schema_version: _portable_json_schema(model.model_json_schema(mode="validation"))
        for schema_version, model in CONTRACT_MODELS.items()
    }


def _portable_json_schema(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _portable_json_schema(child)
            for key, child in value.items()
            if key != "discriminator"
        }
    if isinstance(value, list):
        return [_portable_json_schema(child) for child in value]
    return value


def export(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for schema_version, schema in schemas().items():
        target = output / f"{schema_version}.schema.json"
        target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(output: Path) -> None:
    expected_files = {f"{schema_version}.schema.json" for schema_version in schemas()}
    actual_files = {path.name for path in output.glob("*.schema.json")}
    if actual_files != expected_files:
        raise SystemExit(
            f"contract schema file set differs: expected={sorted(expected_files)} "
            f"actual={sorted(actual_files)}"
        )
    for schema_version, schema in schemas().items():
        expected = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        target = output / f"{schema_version}.schema.json"
        if target.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"contract schema is stale: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export music_ai JSON Schemas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.output:
        export(args.output)
    elif args.check:
        check(args.check)


if __name__ == "__main__":
    main()
