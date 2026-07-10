from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from music_ai_control_plane.database import utc_now
from music_ai_control_plane.models import ApiCredential, Tenant

ALL_SCOPES = frozenset(
    {
        "assets:write",
        "maintenance:write",
        "phrases:write",
        "scores:write",
        "sessions:write",
        "songs:write",
    }
)


@dataclass(frozen=True, slots=True)
class Actor:
    credential_id: UUID
    tenant_id: UUID
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ScopeDeniedError(scope)


class AuthenticationError(RuntimeError):
    pass


class ScopeDeniedError(RuntimeError):
    def __init__(self, scope: str) -> None:
        super().__init__(f"missing required scope: {scope}")
        self.scope = scope


def token_digest(token: str, pepper: str) -> str:
    if len(token) < 32:
        raise ValueError("API tokens must contain at least 32 characters")
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def authenticate(
    session: Session,
    *,
    token: str,
    pepper: str,
    now: datetime | None = None,
) -> Actor:
    timestamp = now or utc_now()
    digest = token_digest(token, pepper)
    row = session.execute(
        select(ApiCredential, Tenant)
        .join(Tenant, Tenant.id == ApiCredential.tenant_id)
        .where(
            ApiCredential.token_digest == digest,
            ApiCredential.revoked_at.is_(None),
            Tenant.deleted_at.is_(None),
            ApiCredential.created_at <= timestamp,
        )
    ).one_or_none()
    if row is None or not hmac.compare_digest(row.ApiCredential.token_digest, digest):
        raise AuthenticationError("invalid or revoked bearer token")
    scopes = frozenset(row.ApiCredential.scopes)
    if not scopes <= ALL_SCOPES:
        raise AuthenticationError("credential contains unknown scopes")
    return Actor(
        credential_id=row.ApiCredential.id,
        tenant_id=row.Tenant.id,
        scopes=scopes,
    )


def ensure_bootstrap_credential(
    session: Session,
    *,
    tenant_slug: str,
    tenant_name: str,
    token: str,
    pepper: str,
    scopes: frozenset[str] = ALL_SCOPES,
) -> Tenant:
    if not scopes <= ALL_SCOPES:
        raise ValueError("bootstrap credential contains unknown scopes")
    tenant = session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        tenant = Tenant(slug=tenant_slug, name=tenant_name)
        session.add(tenant)
        session.flush()
    elif tenant.deleted_at is not None:
        raise ValueError("cannot bootstrap a deleted tenant")

    digest = token_digest(token, pepper)
    credential = session.scalar(select(ApiCredential).where(ApiCredential.token_digest == digest))
    if credential is None:
        session.add(
            ApiCredential(
                tenant_id=tenant.id,
                name="development bootstrap",
                token_digest=digest,
                scopes=sorted(scopes),
            )
        )
    elif credential.tenant_id != tenant.id:
        raise ValueError("bootstrap token is already bound to another tenant")
    session.commit()
    return tenant
