import logging
from datetime import datetime
from typing import Any

import pymssql

from app.config import settings

logger = logging.getLogger(__name__)


def get_sage_sql_connection():
    """Retourne une connexion pymssql vers Sage X3 SQL Server."""
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

    if missing:
        raise ValueError(f"Missing Sage SQL configuration: {', '.join(missing)}")

    # Parser server et port depuis le format "host,port"
    server_parts = settings.SAGE_SQL_SERVER.split(',')
    server = server_parts[0].strip()
    port = int(server_parts[1].strip()) if len(server_parts) > 1 else 1433

    return pymssql.connect(
        server=server,
        port=port,
        user=settings.SAGE_SQL_USER,
        password=settings.SAGE_SQL_PASSWORD,
        database=settings.SAGE_SQL_DATABASE,
        timeout=settings.SAGE_SQL_TIMEOUT_SECONDS,
    )


def lire_programmes_du_jour() -> list[dict[str, Any]]:
    """Lit tous les programmes non confirmés des 2 derniers jours depuis Sage X3.
    Cherche les programmes avec YFLGVAL2_0=1 d'hier et d'aujourd'hui."""
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        database = settings.SAGE_SQL_DATABASE
        schema = settings.SAGE_SQL_SCHEMA

        logger.info(f"[SAGE SQL] Querying {database}.{schema}.YPRGCOLL with YFLGVAL2_0=1")

        cursor.execute(f"USE {database}")
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
            FROM {schema}.YPRGCOLL p
            WHERE p.YFLGVAL2_0 = 1
            AND CAST(p.YDATE_0 AS DATE) >= CAST(DATEADD(day, -1, GETDATE()) AS DATE)
            ORDER BY p.YDATE_0 DESC, p.YTIME_0
            """
        )

        programmes = []
        rows = cursor.fetchall()
        logger.info(f"[SAGE SQL] Query returned {len(rows)} rows")
        for row in rows:
            program_code = (row[0] or "").strip()
            date_value = row[4]
            if isinstance(date_value, datetime):
                date_value = date_value.date()

            heure_raw = (row[5] or "0000").strip()
            heure_fmt = f"{heure_raw[:2]}:{heure_raw[2:4]}" if len(heure_raw) >= 4 else "00:00"
            program_type = "COLLECTION" if (row[6] or "").strip().upper() == "PCOL" else "DELIVERY"

            cursor2 = conn.cursor()
            cursor2.execute(f"USE {database}")
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
                FROM {schema}.YPRGCOLLD d
                WHERE d.YPROGCOLL_0 = %s
                ORDER BY d.YLIGNE_0
                """,
                (program_code,)
            )

            lignes = []
            for l in cursor2.fetchall():
                # Helper to safely convert to float
                def safe_float(val, default=0):
                    if val is None:
                        return default
                    val_str = str(val).strip()
                    if not val_str:
                        return default
                    try:
                        return float(val_str)
                    except (ValueError, TypeError):
                        return default

                lignes.append({
                    "line": l[0],
                    "client_code": (l[1] or "").strip(),
                    "point_livr": (l[2] or "").strip(),
                    "zone": (l[3] or "").strip(),
                    "article": (l[4] or "").strip(),
                    "quantite": safe_float(l[5]),
                    "mode_livr": (l[6] or "").strip(),
                    "num_fiche": (l[7] or "").strip(),
                    "designation": (l[8] or "").strip(),
                    "remboursement": safe_float(l[9]),
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
        schema = settings.SAGE_SQL_SCHEMA

        cursor.execute(
            f"SELECT YPROGCOLL_0, YFLGVAL2_0 FROM [{schema}].[YPRGCOLL] WHERE YPROGCOLL_0 = %s",
            (num_programme.strip(),)
        )
        row = cursor.fetchone()
        if row is None:
            return "NOT_FOUND"

        current_status = row[1]
        if current_status == 2 or str(current_status).strip() == "2":
            return "ALREADY_VALIDATED"

        cursor.execute(
            f"UPDATE [{schema}].[YPRGCOLL] SET YFLGVAL2_0 = 2 WHERE YPROGCOLL_0 = %s",
            (num_programme.strip(),)
        )
        conn.commit()
        logger.info(f"[SAGE SQL] Programme {num_programme} validé — YFLGVAL2_0=2")
        return "OK"
    except Exception as exc:
        logger.error(f"[SAGE SQL] Erreur validation du programme {num_programme}: {exc}")
        return "ERROR"
    finally:
        conn.close()


def lire_tous_programmes_sage() -> list[dict[str, Any]]:
    """Lit TOUS les programmes de Sage X3 sans filtre (pour diagnostic)."""
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        database = settings.SAGE_SQL_DATABASE
        schema = settings.SAGE_SQL_SCHEMA

        cursor.execute(f"USE {database}")
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
                COUNT(d.YLIGNE_0) as line_count
            FROM {schema}.YPRGCOLL p
            LEFT JOIN {schema}.YPRGCOLLD d ON d.YPROGCOLL_0 = p.YPROGCOLL_0
            GROUP BY p.YPROGCOLL_0, p.YFCY_0, p.YLIV_0, p.YMATCAM_0, p.YDATE_0, p.YTIME_0, p.YGFLAG_0, p.YFLGVAL_0, p.YFLGVAL2_0
            ORDER BY p.YDATE_0 DESC, p.YPROGCOLL_0 DESC
            """
        )

        programmes = []
        for row in cursor.fetchall():
            date_value = row[4]
            if isinstance(date_value, datetime):
                date_value = date_value.date()

            programmes.append({
                "program_code": (row[0] or "").strip(),
                "site": (row[1] or "").strip(),
                "sage_driver_code": (row[2] or "").strip(),
                "truck_code": (row[3] or "").strip(),
                "date": str(date_value) if date_value else None,
                "time": (row[5] or "").strip(),
                "yflgval": row[7],
                "yflgval2": row[8],
                "line_count": row[9],
            })

        return programmes
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
