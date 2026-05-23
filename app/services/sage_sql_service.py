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


def ecrire_livraison_sage(
    num_programme: str,
    client_code: str,
    qty_6kg: int,
    qty_12kg: int,
    notes: str = None,
    total_amount_6kg: float = 0,
) -> dict[str, Any]:
    """Écrit UNE SEULE livraison dans Sage X3 immédiatement.

    Appelé après chaque confirmation du driver.
    Vérifie si c'est la dernière ligne → met YFLGVAL2_0=2

    Args:
        num_programme: Code du programme Sage
        client_code: Code client
        qty_6kg: Quantité 6kg confirmée
        qty_12kg: Quantité 12kg confirmée
        notes: Commentaire du driver (YDES_0)
        total_amount_6kg: Montant total 6kg (YSMREMB_0)

    Returns:
        {status: OK/ERROR, detail: message, program_validated: bool}
    """
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        schema = settings.SAGE_SQL_SCHEMA
        database = settings.SAGE_SQL_DATABASE

        logger.info(f"[SAGE SQL] Écriture livraison: {num_programme} / {client_code} → 6kg={qty_6kg}, 12kg={qty_12kg}")

        cursor.execute(f"USE {database}")

        # UPDATE la ligne existante (6kg par défaut ou ligne vierge originale pour ce client)
        cursor.execute(
            f"""
            UPDATE {schema}.YPRGCOLLD
            SET YQTY_0 = %s,
                YSMREMB_0 = CAST(%s AS nvarchar),
                YDES_0 = %s,
                YITMREF_0 = 'G06BI'
            WHERE YPROGCOLL_0 = %s
            AND YBPC_0 = %s
            AND (YITMREF_0 = 'G06BI' OR YITMREF_0 IS NULL OR LTRIM(RTRIM(YITMREF_0)) = '')
            """,
            (qty_6kg, total_amount_6kg, notes or '', num_programme.strip(), client_code)
        )
        logger.info(f"[SAGE SQL] UPDATE {client_code}: {cursor.rowcount} ligne(s) - Qty={qty_6kg}, Montant={total_amount_6kg}, Notes={notes}")

        # INSERT nouvelle ligne pour 12kg si qty > 0
        if qty_12kg > 0:
            cursor.execute(
                f"SELECT MAX(YLIGNE_0) FROM {schema}.YPRGCOLLD WHERE YPROGCOLL_0 = %s",
                (num_programme.strip(),)
            )
            max_line = cursor.fetchone()[0]
            next_line = (max_line or 0) + 1

            cursor.execute(
                f"""
                INSERT INTO {schema}.YPRGCOLLD
                (YPROGCOLL_0, YLIGNE_0, YBPC_0, YQTY_0, YITMREF_0, YSMREMB_0, YDES_0)
                VALUES (%s, %s, %s, %s, 'G1250', CAST(%s AS nvarchar), %s)
                """,
                (num_programme.strip(), next_line, client_code, qty_12kg, 0, notes or '')
            )
            logger.info(f"[SAGE SQL] INSERT {client_code} 12kg: ligne {next_line} - Qty={qty_12kg}, Notes={notes}")

        # Vérifie si TOUTES les lignes du programme sont complétées
        # Une ligne est considérée traitée si son code article (YITMREF_0) est renseigné (non nul et non vide)
        cursor.execute(
            f"""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN YITMREF_0 IS NOT NULL AND LTRIM(RTRIM(YITMREF_0)) <> '' THEN 1 ELSE 0 END) as completed
            FROM {schema}.YPRGCOLLD
            WHERE YPROGCOLL_0 = %s
            """,
            (num_programme.strip(),)
        )
        result = cursor.fetchone()
        total_lines = result[0] if result else 0
        completed_lines = result[1] if result else 0

        program_validated = False
        if total_lines > 0 and completed_lines >= total_lines:
            # Toutes les lignes sont complétées → valider le programme
            cursor.execute(
                f"UPDATE {schema}.YPRGCOLL SET YFLGVAL2_0 = 2 WHERE YPROGCOLL_0 = %s",
                (num_programme.strip(),)
            )
            program_validated = True
            logger.info(f"[SAGE SQL] ✅ Programme {num_programme} VALIDÉ (YFLGVAL2_0=2) — {completed_lines}/{total_lines} lignes")

        conn.commit()

        return {
            "status": "OK",
            "detail": f"Livraison {client_code} écrite dans Sage",
            "program_validated": program_validated,
            "total_lines": total_lines,
            "completed_lines": completed_lines,
        }
    except Exception as exc:
        logger.error(f"[SAGE SQL] Erreur écriture livraison {num_programme}/{client_code}: {exc}")
        conn.rollback()
        return {
            "status": "ERROR",
            "detail": str(exc),
            "program_validated": False,
        }
    finally:
        conn.close()


def ecrire_programme_valide_sage(
    num_programme: str,
    livraisons: list[dict[str, Any]]
) -> dict[str, Any]:
    """Écrit les livraisons validées dans Sage X3 pour un programme.

    Pour chaque livraison:
    - UPDATE la ligne existante avec quantité 6kg
    - INSERT nouvelle ligne pour 12kg si qty > 0
    Marque ensuite le programme validé (YFLGVAL2_0=2).

    Args:
        num_programme: Code du programme Sage
        livraisons: Array de {client_code, quantite_6kg, quantite_12kg, montant_total}

    Returns:
        {status: OK/ERROR, detail: message, updated_lines: count, inserted_lines: count}
    """
    conn = get_sage_sql_connection()
    try:
        cursor = conn.cursor()
        schema = settings.SAGE_SQL_SCHEMA
        database = settings.SAGE_SQL_DATABASE

        logger.info(f"[SAGE SQL] Début écriture programme validé {num_programme}, {len(livraisons)} livraisons")

        updated_count = 0
        inserted_count = 0

        # Récupère le numéro de ligne max pour INSERTs
        cursor.execute(f"USE {database}")
        cursor.execute(
            f"SELECT MAX(YLIGNE_0) FROM {schema}.YPRGCOLLD WHERE YPROGCOLL_0 = %s",
            (num_programme.strip(),)
        )
        max_line = cursor.fetchone()[0]
        next_line = (max_line or 0) + 1

        # Traite chaque livraison
        for livraison in livraisons:
            client_code = (livraison.get("client_code") or "").strip()
            qty_6kg = int(livraison.get("quantite_6kg") or 0)
            qty_12kg = int(livraison.get("quantite_12kg") or 0)
            montant_total = livraison.get("montant_total") or 0

            if not client_code:
                continue

            # UPDATE la ligne 6kg existante (ou ligne vierge originale pour ce client)
            if qty_6kg > 0:
                cursor.execute(f"USE {database}")
                cursor.execute(
                    f"""
                    UPDATE {schema}.YPRGCOLLD
                    SET YQTY_0 = %s,
                        YSMREMB_0 = CAST(%s AS nvarchar),
                        YITMREF_0 = 'G06BI'
                    WHERE YPROGCOLL_0 = %s
                    AND YBPC_0 = %s
                    AND (YITMREF_0 = 'G06BI' OR YITMREF_0 IS NULL OR LTRIM(RTRIM(YITMREF_0)) = '')
                    """,
                    (qty_6kg, montant_total, num_programme.strip(), client_code)
                )
                updated_count += cursor.rowcount
                logger.info(f"[SAGE SQL] UPDATE {client_code} 6kg: {cursor.rowcount} lignes, Qty={qty_6kg}, Montant={montant_total}")

            # INSERT nouvelle ligne pour 12kg si qty > 0
            if qty_12kg > 0:
                cursor.execute(f"USE {database}")
                cursor.execute(
                    f"""
                    INSERT INTO {schema}.YPRGCOLLD
                    (YPROGCOLL_0, YLIGNE_0, YBPC_0, YQTY_0, YITMREF_0, YSMREMB_0)
                    VALUES (%s, %s, %s, %s, 'G1250', CAST(0 AS nvarchar))
                    """,
                    (num_programme.strip(), next_line, client_code, qty_12kg)
                )
                inserted_count += 1
                next_line += 1
                logger.info(f"[SAGE SQL] INSERT {client_code} 12kg: 1 ligne, Qty={qty_12kg}")

        # Marque le programme comme validé
        cursor.execute(f"USE {database}")
        cursor.execute(
            f"UPDATE {schema}.YPRGCOLL SET YFLGVAL2_0 = 2 WHERE YPROGCOLL_0 = %s",
            (num_programme.strip(),)
        )

        conn.commit()
        logger.info(f"[SAGE SQL] Programme {num_programme} validé — {updated_count} UPDATE, {inserted_count} INSERT")

        return {
            "status": "OK",
            "detail": f"Programme {num_programme} écrit dans Sage: {updated_count} lignes mises à jour, {inserted_count} lignes insérées",
            "updated_lines": updated_count,
            "inserted_lines": inserted_count,
        }
    except Exception as exc:
        logger.error(f"[SAGE SQL] Erreur écriture programme {num_programme}: {exc}")
        conn.rollback()
        return {
            "status": "ERROR",
            "detail": str(exc),
            "updated_lines": 0,
            "inserted_lines": 0,
        }
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
