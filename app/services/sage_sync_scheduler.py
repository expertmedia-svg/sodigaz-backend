import asyncio
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import IntegrationSchedule
from app.routers.integration import sync_sage_programs_from_sql
import logging

logger = logging.getLogger(__name__)

SAGE_SQL_SYNC_SCHEDULE_NAME = "sage_sql_daily_sync"


def parse_daily_sync_time(run_time: str) -> time:
    if run_time is None:
        raise ValueError("run_time ne peut pas être vide")
    try:
        parsed = datetime.strptime(run_time, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Le format de l'heure doit être HH:MM") from exc
    return parsed


def calculate_next_run_time(run_time: str, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
    scheduled_time = parse_daily_sync_time(run_time)
    next_run = datetime.combine(now.date(), scheduled_time)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


def get_sage_sql_daily_sync_config(db: Session) -> IntegrationSchedule:
    config = db.query(IntegrationSchedule).filter(IntegrationSchedule.name == SAGE_SQL_SYNC_SCHEDULE_NAME).first()
    if config is not None:
        return config

    enabled = settings.SAGE_SQL_DAILY_SYNC_ENABLED
    run_time = settings.SAGE_SQL_DAILY_SYNC_TIME
    config = IntegrationSchedule(
        name=SAGE_SQL_SYNC_SCHEDULE_NAME,
        enabled=enabled,
        run_time=run_time,
        description="Synchronisation quotidienne automatique des programmes Sage X3",
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_sage_sql_daily_sync_config(db: Session, run_time: Optional[str] = None, enabled: Optional[bool] = None) -> IntegrationSchedule:
    config = get_sage_sql_daily_sync_config(db)
    if run_time is not None:
        parse_daily_sync_time(run_time)
        config.run_time = run_time
    if enabled is not None:
        config.enabled = enabled
    config.updated_at = datetime.now()
    db.commit()
    db.refresh(config)
    return config


async def run_sage_sql_daily_sync_loop() -> None:
    while True:
        db = SessionLocal()
        try:
            config = get_sage_sql_daily_sync_config(db)
            if not config.enabled:
                logger.debug("[SAGE SQL SCHEDULER] Synchronisation automatique désactivée, attente de 60 secondes.")
                await asyncio.sleep(60)
                continue

            next_run = calculate_next_run_time(config.run_time)
            delay = (next_run - datetime.now()).total_seconds()
            logger.info(
                "[SAGE SQL SCHEDULER] Prochaine synchronisation prévue à %s (dans %.0f secondes). "
                "Temps de sync configuré: %s",
                next_run.isoformat(),
                delay,
                config.run_time
            )
        finally:
            db.close()

        if delay > 0:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                logger.info("[SAGE SQL SCHEDULER] Tâche annulée avant execution.")
                return

        db = SessionLocal()
        try:
            config = get_sage_sql_daily_sync_config(db)
            if not config.enabled:
                logger.info("[SAGE SQL SCHEDULER] Synchronisation désactivée juste avant execution.")
                continue
        finally:
            db.close()

        db = SessionLocal()
        try:
            logger.info("[SAGE SQL SCHEDULER] ========== DÉBUT SYNCHRONISATION ==========")
            logger.info("[SAGE SQL SCHEDULER] Heure de sync: %s | Heure actuelle: %s",
                       config.run_time, datetime.now().strftime("%H:%M:%S"))
            result = sync_sage_programs_from_sql(db)

            logger.info("[SAGE SQL SCHEDULER] ========== SYNC TERMINÉE ==========")
            logger.info("[SAGE SQL SCHEDULER] Résultats: Synced=%d, Created=%d, Updated=%d, Errors=%d",
                       result.get("synced", 0),
                       result.get("created", 0),
                       result.get("updated", 0),
                       len(result.get("errors", [])))

            if result.get("errors"):
                logger.warning("[SAGE SQL SCHEDULER] Erreurs détectées:")
                for err in result.get("errors", []):
                    logger.warning("  - Programme %s: %s",
                                 err.get("program_code"),
                                 err.get("error"))
        except Exception as exc:
            logger.error("[SAGE SQL SCHEDULER] ========== ERREUR CRITIQUE ==========")
            logger.exception("[SAGE SQL SCHEDULER] Exception lors de la synchronisation: %s", exc)
            logger.error("[SAGE SQL SCHEDULER] Type: %s | Message: %s", type(exc).__name__, str(exc))
        finally:
            db.close()


def start_sage_sql_sync_task(app) -> None:
    if hasattr(app.state, "sage_sql_sync_task") and app.state.sage_sql_sync_task is not None:
        return
    app.state.sage_sql_sync_task = asyncio.create_task(run_sage_sql_daily_sync_loop())


async def stop_sage_sql_sync_task(app) -> None:
    task = getattr(app.state, "sage_sql_sync_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("[SAGE SQL SCHEDULER] Tâche arrêtée.")
    app.state.sage_sql_sync_task = None
