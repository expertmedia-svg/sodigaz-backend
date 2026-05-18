import logging
from datetime import datetime
from typing import Any

import pyodbc

from app.config import settings

logger = logging.getLogger(__name__)


def get_sage_sql_connection():
    """Retourne une connexion pyodbc vers Sage X3 SQL Server."""
    missing = []
    if not settings.SAGE_SQL_SERVER:
        missing.append("SAGE_SQL_SERVER")
    if not settings.SAGE_SQL_DATABASE:
        missing.append("SAGE_SQL_DATABASE")
    if not settings.SAGE_SQL_SCHEMA:
        missing.append("SAGE_SQL_SCHEMA")
    if not settings.SAGE_SQL_USER:
        missing.append("SAGE_SQL_USER")
    if not settings.SAGE_SQL_PASSWORD:
        missing.append("SAGE_SQL_PASSWORD")
    if not settings.SAGE_SQL_DRIVER:
        missing.append("SAGE_SQL_DRIVER")

    if missing:
        raise ValueError(f"Missing Sage SQL configuration: {', '.join(missing)}")

    conn_str = (
        f"DRIVER={{{settings.SAGE_SQL_DRIVER}}};"
        f"SERVER={settings.SAGE_SQL_SERVER};"
        f"DATABASE={settings.SAGE_SQL_DATABASE};"
        f"UID={settings.SAGE_SQL_USER};"
        f"PWD={settings.SAGE_SQL_PASSWORD};"
        f"Connection Timeout={settings.SAGE_SQL_TIMEOUT_SECONDS};"
    )

    return pyodbc.connect(conn_str)


def lire_programmes_du_jour() -> list[dict[str, Any]]:
    """Lit tous les programmes du jour non confirmés depuis Sage X3."""
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        db = settings.SAGE_SQL_DATABASE
        schema = settings.SAGE_SQL_SCHEMA

        cursor.execute(
            f"""
            SELECT
                p.YPROGCOLL_0,
                p.YFCY_0,
                p.YLIV_0,
                p.YMATCAM_0,
                p.YDATE_0,
                p.YTIME_0,
                p.YGFLAG_0,
                p.YFLGVAL_0,
                p.YFLGVAL2_0,
                p.YTACHERON1_0,
                p.YTACHERON2_0
            FROM {db}.{schema}.YPRGCOLL p
            WHERE p.YFLGVAL2_0 = 1
            AND CAST(p.YDATE_0 AS DATE) = CAST(GETDATE() AS DATE)
            ORDER BY p.YTIME_0
            """
        )

        programmes = []
        for row in cursor.fetchall():
            program_code = (row[0] or "").strip()
            date_value = row[4]
            if isinstance(date_value, datetime):
                date_value = date_value.date()

            heure_raw = (row[5] or "0000").strip()
            heure_fmt = f"{heure_raw[:2]}:{heure_raw[2:4]}" if len(heure_raw) >= 4 else "00:00"
            program_type = "COLLECTION" if (row[6] or "").strip().upper() == "PCOL" else "DELIVERY"

            cursor2 = conn.cursor()
            cursor2.execute(
                f"""
                SELECT
                    d.YLIGNE_0,
                    d.YBPC_0,
                    d.YPLV_0,
                    d.YQUARTIER_0,
                    d.YITMREF_0,
                    d.YQTY_0,
                    d.MDL_0,
                    d.YNUMFICHE_0,
                    d.YDES_0,
                    d.YSMREMB_0
                FROM {db}.{schema}.YPRGCOLLD d
                WHERE d.YPROGCOLL_0 = ?
                ORDER BY d.YLIGNE_0
                """,
                program_code,
            )

            lignes = []
            for l in cursor2.fetchall():
                lignes.append({
                    "line": l[0],
                    "client_code": (l[1] or "").strip(),
                    "point_livr": (l[2] or "").strip(),
                    "zone": (l[3] or "").strip(),
                    "article": (l[4] or "").strip(),
                    "quantite": float(l[5]) if l[5] is not None else 0,
                    "mode_livr": (l[6] or "").strip(),
                    "num_fiche": (l[7] or "").strip(),
                    "designation": (l[8] or "").strip(),
                    "remboursement": float(l[9]) if l[9] is not None else 0,
                })

            programmes.append({
                "program_code": program_code,
                "program_type": program_type,
                "site": (row[1] or "").strip(),
                "sage_driver_code": (row[2] or "").strip(),
                "truck_code": (row[3] or "").strip(),
                "date": date_value,
                "time": heure_fmt,
                "status": "active",
                "yflgval": row[7],
                "yflgval2": row[8],
                "tacheron1": (row[9] or "").strip(),
                "tacheron2": (row[10] or "").strip(),
                "lines": lignes,
            })

        return programmes
    finally:
        conn.close()


def valider_programme_sage(num_programme: str) -> str:
    """Met à jour YFLGVAL2_0 = 2 pour un programme Sage X3."""
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        db = settings.SAGE_SQL_DATABASE
        schema = settings.SAGE_SQL_SCHEMA

        cursor.execute(
            f"SELECT YPROGCOLL_0, YFLGVAL2_0 FROM {db}.{schema}.YPRGCOLL WHERE YPROGCOLL_0 = ?",
            num_programme.strip(),
        )
        row = cursor.fetchone()
        if row is None:
            return "NOT_FOUND"

        current_status = row[1]
        if current_status == 2 or str(current_status).strip() == "2":
            return "ALREADY_VALIDATED"

        cursor.execute(
            f"UPDATE {db}.{schema}.YPRGCOLL SET YFLGVAL2_0 = 2 WHERE YPROGCOLL_0 = ?",
            num_programme.strip(),
        )
        conn.commit()
        logger.info(f"[SAGE SQL] Programme {num_programme} validé — YFLGVAL2_0=2")
        return "OK"
    except Exception as exc:
        logger.error(f"[SAGE SQL] Erreur validation du programme {num_programme}: {exc}")
        return "ERROR"
    finally:
        conn.close()


def check_sage_sql_connection() -> dict:
    """Teste la connexion SQL vers Sage X3."""
    try:
        conn = get_sage_sql_connection()
        conn.close()
        return {
            "status": "healthy",
            "mode": "sql",
            "detail": "Connexion SQL Sage X3 réussie.",
            "server": settings.SAGE_SQL_SERVER,
            "database": settings.SAGE_SQL_DATABASE,
        }
    except Exception as exc:
        logger.warning(f"[SAGE SQL] Échec de connexion SQL: {exc}")
        return {
            "status": "unreachable",
            "mode": "sql",
            "detail": str(exc),
        }
