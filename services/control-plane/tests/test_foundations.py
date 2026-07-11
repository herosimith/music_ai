from __future__ import annotations

import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from music_ai_control_plane.config import Settings
from music_ai_control_plane.security import token_digest
from music_ai_control_plane.storage import LocalObjectStore
from pydantic import ValidationError

PEPPER = "foundation-test-pepper-0123456789abcdef"


def test_production_settings_require_postgres_migrations_and_no_static_bootstrap() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://app:password@db/music_ai",
        token_pepper=PEPPER,
        auto_create_schema=False,
    )
    assert settings.environment == "production"

    with pytest.raises(ValidationError, match="migrations"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://app:password@db/music_ai",
            token_pepper=PEPPER,
            auto_create_schema=True,
        )
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(
            environment="production",
            database_url="sqlite:///unsafe.db",
            token_pepper=PEPPER,
            auto_create_schema=False,
        )
    with pytest.raises(ValidationError, match="maintenance interval"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://app:password@db/music_ai",
            token_pepper=PEPPER,
            auto_create_schema=False,
            raw_audio_ttl_seconds=300,
            maintenance_interval_seconds=300,
        )


def test_bootstrap_configuration_is_all_or_nothing() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(
            environment="test",
            token_pepper=PEPPER,
            bootstrap_tenant_slug="partial",
        )
    with pytest.raises(ValidationError, match="coach base URL"):
        Settings(
            environment="test",
            token_pepper=PEPPER,
            coach_model="gpt-test.v1",
        )


def test_token_digest_is_peppered_and_rejects_short_tokens() -> None:
    token = "token-value-0123456789abcdefghijkl"
    assert token_digest(token, PEPPER) == token_digest(token, PEPPER)
    assert token_digest(token, PEPPER) != token_digest(token, "x" * 32)
    with pytest.raises(ValueError, match="32"):
        token_digest("short", PEPPER)


def test_local_object_store_is_idempotent_and_blocks_path_escape(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    store.put("tenants/one/item", b"payload")
    store.put("tenants/one/item", b"payload")
    assert store.exists("tenants/one/item")
    target = tmp_path / "objects" / "tenants" / "one" / "item"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="different content"):
        store.put("tenants/one/item", b"changed")
    with pytest.raises(ValueError, match="invalid path segment"):
        store.put("../outside", b"payload")
    for key in ("..", ".", "nested/../outside", "nested//item"):
        with pytest.raises(ValueError, match="invalid path segment"):
            store.put(key, b"payload")
    store.delete("tenants/one/item")
    store.delete("tenants/one/item")
    assert not store.exists("tenants/one/item")


def test_local_object_store_does_not_overwrite_during_concurrent_puts(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.put, "tenant/item", payload) for payload in (b"first", b"second")
        ]
    errors = [future.exception() for future in futures if future.exception() is not None]
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    target = tmp_path / "objects" / "tenant" / "item"
    assert target.read_bytes() in {b"first", b"second"}


def test_local_object_store_rejects_symbolic_link_targets(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    protected = root / "protected"
    protected.write_bytes(b"keep")
    (root / "link").symlink_to(protected)
    with pytest.raises(ValueError, match="symbolic link"):
        store.delete("link")
    assert protected.read_bytes() == b"keep"

    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked-directory").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        store.put("linked-directory/item", b"payload")
