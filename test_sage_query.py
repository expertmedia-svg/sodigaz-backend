#!/usr/bin/env python3
"""
Direct test of Sage SQL Server YPRGCOLL query using pymssql
"""
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
SAGE_SQL_DRIVER = os.getenv('SAGE_SQL_DRIVER', '')

print("=" * 80)
print("Testing Sage SQL Server Connection and YPRGCOLL Query")
print("=" * 80)

# Parse server and port
if ',' in SAGE_SQL_SERVER:
    server, port = SAGE_SQL_SERVER.split(',')
    port = int(port.strip())
else:
    server = SAGE_SQL_SERVER
    port = 1433

print(f"\n[CONFIG] Configuration:")
print(f"  Server: {server}:{port}")
print(f"  Database: {SAGE_SQL_DATABASE}")
print(f"  Schema: {SAGE_SQL_SCHEMA}")
print(f"  User: {SAGE_SQL_USER}")

try:
    print(f"\n[CONNECT] Connecting to SQL Server...")
    conn = pymssql.connect(
        server=server,
        port=port,
        user=SAGE_SQL_USER,
        password=SAGE_SQL_PASSWORD,
        database=SAGE_SQL_DATABASE,
        timeout=30
    )
    print(f"[SUCCESS] Connection successful!")

    cursor = conn.cursor()

    # Test 1: List tables in schema
    print(f"\n[TEST 1] List tables in {SAGE_SQL_SCHEMA} schema...")
    cursor.execute(f"""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{SAGE_SQL_SCHEMA}'
    """)
    tables = cursor.fetchall()
    print(f"  Found {len(tables)} table(s):")
    for table in tables:
        print(f"    - {table[0]}")

    # Test 2: Try query WITHOUT database name (already connected to database)
    print(f"\n[TEST 2] Query YPRGCOLL WITHOUT database name...")
    schema = SAGE_SQL_SCHEMA

    query = f"""
        SELECT DISTINCT UPPER(YLIV_0) as yliv
        FROM [{schema}].[YPRGCOLL]
        WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
        ORDER BY yliv
    """

    print(f"  Query: {query}")
    cursor.execute(query)

    rows = cursor.fetchall()
    print(f"[SUCCESS] Query successful! Found {len(rows)} driver code(s):")
    for row in rows[:10]:  # Show first 10
        print(f"    - {row[0]}")
    if len(rows) > 10:
        print(f"    ... and {len(rows) - 10} more")

    # Test 3: Query with YMATCAM (also without database name)
    print(f"\n[TEST 3] Query YPRGCOLL with YLIV and YMATCAM...")
    query2 = f"""
        SELECT DISTINCT
            UPPER(YLIV_0) as sage_driver_code,
            UPPER(YMATCAM_0) as truck_code,
            YPROGCOLL_0 as program_code
        FROM [{schema}].[YPRGCOLL]
        WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
        AND YMATCAM_0 IS NOT NULL AND YMATCAM_0 != ''
        ORDER BY sage_driver_code, truck_code
    """

    print(f"  Query: {query2}")
    cursor.execute(query2)

    rows2 = cursor.fetchall()
    print(f"[SUCCESS] Query successful! Found {len(rows2)} program row(s):")
    for row in rows2[:5]:  # Show first 5
        print(f"    - Driver: {row[0]}, Truck: {row[1]}, Program: {row[2]}")
    if len(rows2) > 5:
        print(f"    ... and {len(rows2) - 5} more")

    # Test 4: Try with database name using USE statement
    print(f"\n[TEST 4] Query YPRGCOLL with USE statement...")
    query3 = f"""
        USE SAGEX3V12
        SELECT DISTINCT UPPER(YLIV_0)
        FROM [{schema}].[YPRGCOLL]
        WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
        ORDER BY YLIV_0
    """

    print(f"  Query (with USE): {query3}")
    try:
        cursor.execute(query3)
        rows3 = cursor.fetchall()
        print(f"[SUCCESS] Query with USE statement successful! Found {len(rows3)} driver code(s)")
    except Exception as e:
        print(f"[NOTE] USE statement approach didn't work: {e}")

    conn.close()
    print(f"\n[RESULT] All tests passed!")

except pymssql.DatabaseError as e:
    print(f"\n[ERROR] Database Error: {e}")
    import traceback
    traceback.print_exc()
except pymssql.OperationalError as e:
    print(f"\n[ERROR] Connection Error: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"\n[ERROR] Error: {e}")
    import traceback
    traceback.print_exc()
