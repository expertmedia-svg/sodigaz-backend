#!/usr/bin/env python3
"""
Diagnostic script to verify YLIV/YMATCAM population in programs
Run this on production or dev to check current state
"""

import sqlite3
from datetime import datetime, timedelta
import sys


def check_database(db_path="dev.db"):
    """Check programs for YLIV/YMATCAM population"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("=" * 100)
        print(f"DATABASE DIAGNOSTIC: {db_path}")
        print("=" * 100)
        print()

        # Check schema
        cursor.execute("PRAGMA table_info(programs)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        print("[OK] Database schema check:")
        print(f"  - yliv column exists: {'yliv' in columns}")
        print(f"  - ymatcam column exists: {'ymatcam' in columns}")
        print()

        # Total programs
        cursor.execute("SELECT COUNT(*) FROM programs")
        total = cursor.fetchone()[0]
        print(f"Total programs in database: {total}")

        if total == 0:
            print("  [WARN] No programs found - database may be empty")
            return

        print()
        print("-" * 100)
        print("PROGRAMS WITH EMPTY YLIV/YMATCAM (potential issue):")
        print("-" * 100)

        cursor.execute("""
            SELECT id, program_code, yliv, ymatcam, status, created_at
            FROM programs
            WHERE yliv IS NULL OR yliv = '' OR ymatcam IS NULL OR ymatcam = ''
            ORDER BY created_at DESC
            LIMIT 20
        """)

        empty_count = 0
        for row in cursor.fetchall():
            empty_count += 1
            yliv = row[2] or "<null>"
            ymatcam = row[3] or "<null>"
            print(f"ID: {row[0]:<4} | Code: {row[1]:<20} | YLIV: {yliv:<15} | YMATCAM: {ymatcam:<15} | Status: {row[4]:<10} | Created: {row[5]}")

        if empty_count == 0:
            print("  [OK] No programs with empty YLIV/YMATCAM found")
        else:
            print(f"\n  [WARN] Found {empty_count} programs with missing codes")

        print()
        print("-" * 100)
        print("RECENT PROGRAMS WITH POPULATED YLIV/YMATCAM (correct state):")
        print("-" * 100)

        cursor.execute("""
            SELECT id, program_code, yliv, ymatcam, status, created_at
            FROM programs
            WHERE yliv IS NOT NULL AND yliv != '' AND ymatcam IS NOT NULL AND ymatcam != ''
            ORDER BY created_at DESC
            LIMIT 10
        """)

        populated_count = 0
        for row in cursor.fetchall():
            populated_count += 1
            print(f"ID: {row[0]:<4} | Code: {row[1]:<20} | YLIV: {row[2]:<15} | YMATCAM: {row[3]:<15} | Status: {row[4]:<10} | Created: {row[5]}")

        if populated_count == 0:
            print("  [WARN] No programs with populated codes found")
        else:
            print(f"\n  [OK] Found {populated_count} programs with proper codes")

        print()
        print("-" * 100)
        print("STATISTICS:")
        print("-" * 100)

        cursor.execute("SELECT COUNT(*) FROM programs WHERE (yliv IS NULL OR yliv = '') AND (ymatcam IS NULL OR ymatcam = '')")
        both_empty = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM programs WHERE yliv IS NOT NULL AND yliv != '' AND ymatcam IS NOT NULL AND ymatcam != ''")
        both_populated = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM programs WHERE (yliv IS NOT NULL AND yliv != '') XOR (ymatcam IS NOT NULL AND ymatcam != '')")
        one_empty = cursor.fetchone()[0]

        print(f"  Programs with BOTH codes populated: {both_populated:<4} ({100*both_populated/max(total, 1):.1f}%)")
        print(f"  Programs with BOTH codes missing:  {both_empty:<4} ({100*both_empty/max(total, 1):.1f}%)")
        print(f"  Programs with ONLY ONE code:      {one_empty:<4} ({100*one_empty/max(total, 1):.1f}%)")

        print()
        print("=" * 100)

        if both_populated > 0:
            print("[OK] DIAGNOSIS: Code fix is working - programs have YLIV/YMATCAM populated")
        elif both_empty > 0:
            print("[ERROR] DIAGNOSIS: Programs missing YLIV/YMATCAM - backend code may need deployment")

        print("=" * 100)

        conn.close()

    except Exception as e:
        print(f"[ERROR] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "dev.db"
    check_database(db)
