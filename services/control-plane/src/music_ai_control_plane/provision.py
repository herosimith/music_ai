from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence
from uuid import UUID

from music_ai_control_plane.config import Settings
from music_ai_control_plane.database import Database
from music_ai_control_plane.security import register_tenant_credential


def provision_tenant(
    settings: Settings,
    *,
    tenant_slug: str,
    tenant_name: str,
    credential_name: str,
    token: str,
) -> UUID:
    database = Database(settings.database_url)
    try:
        with database.session() as session:
            tenant = register_tenant_credential(
                session,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                credential_name=credential_name,
                token=token,
                pepper=settings.token_pepper.get_secret_value(),
            )
            return tenant.id
    finally:
        database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision a tenant API credential")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--credential-name", default="operator provisioned")
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        help="Read the token from stdin instead of a hidden terminal prompt",
    )
    arguments = parser.parse_args(argv)
    token = _read_token(arguments.token_stdin)
    tenant_id = provision_tenant(
        Settings(),
        tenant_slug=arguments.tenant_slug,
        tenant_name=arguments.tenant_name,
        credential_name=arguments.credential_name,
        token=token,
    )
    print(json.dumps({"tenant_id": str(tenant_id), "tenant_slug": arguments.tenant_slug}))
    return 0


def _read_token(from_stdin: bool) -> str:
    token = sys.stdin.read().strip() if from_stdin else getpass.getpass("API token: ").strip()
    if len(token) < 32:
        raise ValueError("API token must contain at least 32 characters")
    return token


if __name__ == "__main__":
    raise SystemExit(main())
