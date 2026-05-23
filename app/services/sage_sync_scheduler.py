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

SAGE_SQL_SYNC_STATUS = {
    "last_run_time": None,
    "last_run_result": None,
    "last_run_error": None,
    "last_trigger_attempt": None
}


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
    last_run_date = None
    logger.info("[SAGE SQL SCHEDULER] Démarrage de la boucle de synchronisation quotidienne.")
    
    while True:
        try:
            db = SessionLocal()
            try:
                config = get_sage_sql_daily_sync_config(db)
                enabled = config.enabled
                run_time = config.run_time
            finally:
                db.close()

            if not enabled:
                await asyncio.sleep(10)
                continue

            try:
                scheduled_time = datetime.strptime(run_time, "%H:%M").time()
            except Exception:
                await asyncio.sleep(10)
                continue

            now = datetime.now()
            if now.hour == scheduled_time.hour and now.minute == scheduled_time.minute:
                current_date = now.date()
                if last_run_date != current_date:
                    last_run_date = current_date
                    SAGE_SQL_SYNC_STATUS["last_trigger_attempt"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    
                    db = SessionLocal()
                    try:
                        logger.info("[SAGE SQL SCHEDULER] ========== DÉBUT SYNCHRONISATION ==========")
                        logger.info("[SAGE SQL SCHEDULER] Heure de sync: %s | Heure actuelle: %s",
                                   run_time, now.strftime("%H:%M:%S"))
                        result = sync_sage_programs_from_sql(db)
                        logger.info("[SAGE SQL SCHEDULER] ========== SYNC TERMINÉE ==========")
                        logger.info("[SAGE SQL SCHEDULER] Résultats: Synced=%d, Created=%d, Updated=%d, Errors=%d",
                                   result.get("synced", 0),
                                   result.get("created", 0),
                                   result.get("updated", 0),
                                   len(result.get("errors", [])))
                        
                        SAGE_SQL_SYNC_STATUS["last_run_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                        SAGE_SQL_SYNC_STATUS["last_run_result"] = {
                            "synced": result.get("synced", 0),
                            "created": result.get("created", 0),
                            "updated": result.get("updated", 0),
                            "errors_count": len(result.get("errors", []))
                        }
                        SAGE_SQL_SYNC_STATUS["last_run_error"] = None
                        
                        if result.get("errors"):
                            logger.warning("[SAGE SQL SCHEDULER] Erreurs détectées:")
                            for err in result.get("errors", []):
                                logger.warning("  - Programme %s: %s",
                                             err.get("program_code"),
                                             err.get("error"))
                    except Exception as exc:
                        logger.error("[SAGE SQL SCHEDULER] ========== ERREUR CRITIQUE ==========")
                        logger.exception("[SAGE SQL SCHEDULER] Exception lors de la synchronisation: %s", exc)
                        SAGE_SQL_SYNC_STATUS["last_run_error"] = str(exc)
                    finally:
                        db.close()

            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("[SAGE SQL SCHEDULER] Tâche annulée.")
            break
        except Exception as e:
            logger.error(f"[SAGE SQL SCHEDULER] Erreur dans la boucle: {e}")
            await asyncio.sleep(10)


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
