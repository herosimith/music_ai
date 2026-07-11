from __future__ import annotations

import logging
import signal
from dataclasses import dataclass
from threading import Event

from sqlalchemy import select

from music_ai_control_plane.config import Settings
from music_ai_control_plane.database import Database
from music_ai_control_plane.models import Tenant
from music_ai_control_plane.service import ControlPlaneService
from music_ai_control_plane.storage import LocalObjectStore, ObjectStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MaintenanceSummary:
    tenants: int
    expired_audio: int
    completed_tasks: int
    failed_tasks: int


def run_maintenance_once(
    settings: Settings,
    object_store: ObjectStore | None = None,
) -> MaintenanceSummary:
    database = Database(settings.database_url)
    store = object_store or LocalObjectStore(settings.object_store_root)
    try:
        with database.session() as session:
            tenant_ids = list(
                session.scalars(select(Tenant.id).where(Tenant.deleted_at.is_(None)))
            )
        expired_audio = 0
        completed_tasks = 0
        failed_tasks = 0
        for tenant_id in tenant_ids:
            with database.session() as session:
                service = ControlPlaneService(session, store, settings)
                expired_audio += service.expire_raw_audio(tenant_id)
                completed, failed = service.process_deletions(tenant_id)
                completed_tasks += completed
                failed_tasks += failed
        return MaintenanceSummary(
            tenants=len(tenant_ids),
            expired_audio=expired_audio,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
        )
    finally:
        database.dispose()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    stopped = Event()

    def stop(signum, frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped.is_set():
        try:
            summary = run_maintenance_once(settings)
            logger.info(
                "maintenance tenants=%d expired_audio=%d completed_tasks=%d failed_tasks=%d",
                summary.tenants,
                summary.expired_audio,
                summary.completed_tasks,
                summary.failed_tasks,
            )
        except Exception:
            logger.exception("maintenance pass failed")
        stopped.wait(settings.maintenance_interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
