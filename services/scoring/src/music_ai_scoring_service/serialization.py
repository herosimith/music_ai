from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal

from pydantic import BaseModel


def canonical_model_bytes(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def quantize(value: float) -> float:
    rounded = float(Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))
    return 0.0 if rounded == 0 else rounded
