import pymssql
import os
from dotenv import load_dotenv

load_dotenv()

# Get configuration from environment
SAGE_SQL_SERVER = os.getenv('SAGE_SQL_SERVER', '')
SAGE_SQL_DATABASE = os.getenv('SAGE_SQL_DATABASE', 'x3v12')
SAGE_SQL_SCHEMA = os.getenv('SAGE_SQL_SCHEMA', 'SODIGAZG')
SAGE_SQL_USER = os.getenv('SAGE_SQL_USER', '')
SAGE_SQL_PASSWORD = os.getenv('SAGE_SQL_PASSWORD', '')

if ',' in SAGE_SQL_SERVER:
    server, port = SAGE_SQL_SERVER.split(',')
    port = int(port.strip())
else:
    server = SAGE_SQL_SERVER
    port = 1433

print(f"Connecting to SQL Server: {server}:{port} ...")
try:
    conn = pymssql.connect(
        server=server,
        port=port,
        user=SAGE_SQL_USER,
        password=SAGE_SQL_PASSWORD,
        database=SAGE_SQL_DATABASE,
        timeout=30
    )
    print("SUCCESS: Connection established!")
    
    cursor = conn.cursor()
    cursor.execute(f"USE {SAGE_SQL_DATABASE}")
    
    num_programme = 'PCOL-CA006-070723-1306'
    client_code = '122236'
    qty_12kg = 20
    total_amount_12kg = 33520.0
    notes = 'Test injection direct'
    
    print("\n--- Current lines in Sage for this program ---")
    cursor.execute(
        f"SELECT YLIGNE_0, YBPC_0, YPLV_0, YITMREF_0, YQTY_0, YSMREMB_0, YDES_0 FROM {SAGE_SQL_SCHEMA}.YPRGCOLLD WHERE YPROGCOLL_0 = %s ORDER BY YLIGNE_0",
        (num_programme,)
    )
    lines = cursor.fetchall()
    for l in lines:
        print(f"Ligne {l[0]}: Client={l[1]}, PLV={l[2]}, Article={l[3]}, Qty={l[4]}, Montant={l[5]}, Notes={l[6]}")
        
    print("\nRetrieving full original line for client to copy fields...")
    cursor.execute(
        f"""
        SELECT TOP 1 
            YPLV_0, YQUARTIER_0, YDATE_0, SOHNUM_0, SOPLIN_0, YNUMFICHE_0, MDL_0, CREUSR_0
        FROM {SAGE_SQL_SCHEMA}.YPRGCOLLD
        WHERE YPROGCOLL_0 = %s
        AND YBPC_0 = %s
        """,
        (num_programme, client_code)
    )
    orig = cursor.fetchone()
    if orig:
        yplv_val, yquartier_val, ydate_val, sohnum_val, soplin_val, ynumfiche_val, mdl_val, creusr_val = orig
        print(f"Copied fields: PLV='{yplv_val}', Quartier='{yquartier_val}', Date='{ydate_val}', Order='{sohnum_val}', OrderLine={soplin_val}, Fiche='{ynumfiche_val}', Mode='{mdl_val}', User='{creusr_val}'")
    else:
        print("No original line found!")
        yplv_val, yquartier_val, ydate_val, sohnum_val, soplin_val, ynumfiche_val, mdl_val, creusr_val = ('', ' ', None, ' ', 0, ' ', 'CR', 'LOG32')

    print("\nCalculating next line number...")
    cursor.execute(
        f"SELECT MAX(YLIGNE_0) FROM {SAGE_SQL_SCHEMA}.YPRGCOLLD WHERE YPROGCOLL_0 = %s",
        (num_programme,)
    )
    max_line = cursor.fetchone()[0]
    next_line = (max_line or 0) + 1
    print(f"MAX line is {max_line}, Next line will be {next_line}")
    
    print("\nTrying to INSERT 12kg line with copied fields, GETDATE(), and NEWID()...")
    try:
        cursor.execute(
            f"""
            INSERT INTO {SAGE_SQL_SCHEMA}.YPRGCOLLD
            (YPROGCOLL_0, YLIGNE_0, YBPC_0, YPLV_0, YQUARTIER_0, YDATE_0, SOHNUM_0, SOPLIN_0, 
             YITMREF_0, YQTY_0, YNUMFICHE_0, YDES_0, MDL_0, CREUSR_0, UPDUSR_0, YSMREMB_0, CREDATTIM_0, UPDDATTIM_0, AUUID_0)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'G1250', %s, %s, %s, %s, %s, 'LOG32', CAST(%s AS nvarchar), GETDATE(), GETDATE(), NEWID())
            """,
            (
                num_programme,
                next_line,
                client_code,
                yplv_val,
                yquartier_val,
                ydate_val,
                sohnum_val,
                soplin_val,
                qty_12kg,
                ynumfiche_val,
                notes,
                mdl_val,
                creusr_val,
                total_amount_12kg
            )
        )
        print(f"INSERT statement completed. Row count: {cursor.rowcount}")
        conn.commit()
        print("Transaction COMMITTED!")
    except Exception as ie:
        print(f"INSERT FAILED WITH EXCEPTION: {ie}")
        conn.rollback()

    print("\nChecking lines again after insert/commit...")
    cursor.execute(
        f"SELECT YLIGNE_0, YBPC_0, YPLV_0, YITMREF_0, YQTY_0, YSMREMB_0, YDES_0 FROM {SAGE_SQL_SCHEMA}.YPRGCOLLD WHERE YPROGCOLL_0 = %s ORDER BY YLIGNE_0",
        (num_programme,)
    )
    lines = cursor.fetchall()
    for l in lines:
        print(f"Ligne {l[0]}: Client={l[1]}, PLV={l[2]}, Article={l[3]}, Qty={l[4]}, Montant={l[5]}, Notes={l[6]}")

    conn.close()
    
except Exception as e:
    print(f"Connection failed: {e}")
