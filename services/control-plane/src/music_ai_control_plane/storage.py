from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class ObjectStore(Protocol):
    def put(self, key: str, payload: bytes) -> None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, payload: bytes) -> None:
        target = self._target(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != payload:
                raise ValueError("object key already exists with different content")
            return
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}-{uuid4().hex}")
        try:
            temporary.write_bytes(payload)
            temporary.chmod(0o600)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != payload:
                    raise ValueError("object key already exists with different content") from None
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        self._target(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._target(key).is_file()

    def _target(self, key: str) -> Path:
        if not key or key.startswith("/"):
            raise ValueError("object key must be relative")
        if any(segment in {"", ".", ".."} for segment in key.split("/")):
            raise ValueError("object key contains an invalid path segment")
        candidate = self.root / key
        parent = candidate.parent.resolve()
        if not parent.is_relative_to(self.root):
            raise ValueError("object key escapes the storage root")
        target = parent / candidate.name
        if target.is_symlink():
            raise ValueError("object key cannot reference a symbolic link")
        return target


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, payload: bytes) -> None:
        existing = self.objects.get(key)
        if existing is not None and existing != payload:
            raise ValueError("object key already exists with different content")
        self.objects[key] = payload

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects
