#!/usr/bin/env python3
"""Diagnostic script to check Sage SQL program sync issues."""

import sys
import os
from datetime import datetime, date

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.services.sage_sql_service import (
    lire_programmes_du_jour,
    lire_tous_programmes_sage,
    check_sage_sql_connection,
)
from app.database import SessionLocal
from app.models import Depot, Program

def main():
    print("=" * 80)
    print("SAGE SQL DIAGNOSTIC - Program Sync Troubleshooting")
    print("=" * 80)
    print()

    # 1. Check connection
    print("[1] Testing Sage SQL Connection")
    print("-" * 80)
    conn_result = check_sage_sql_connection()
    print(f"Status: {conn_result['status']}")
    if conn_result['status'] == "healthy":
        print(f"✓ Connected to {conn_result['server']} / {conn_result['database']}")
    else:
        print(f"✗ Connection failed: {conn_result.get('detail')}")
        sys.exit(1)
    print()

    # 2. Get all programs from Sage
    print("[2] Reading ALL Programs from Sage SQL")
    print("-" * 80)
    try:
        all_programs = lire_tous_programmes_sage()
        print(f"Total programs in Sage: {len(all_programs)}")
        print()

        if all_programs:
            print("Sample programs (first 5):")
            for prog in all_programs[:5]:
                print(f"  - {prog['program_code']}")
                print(f"    Site: {prog['site']} | Driver: {prog['sage_driver_code']} | Truck: {prog['truck_code']}")
                print(f"    Date: {prog['date']} | Time: {prog['time']}")
                print(f"    Flags: YFLGVAL2={prog['yflgval2']} | Line count: {prog['line_count']}")
                print()
    except Exception as e:
        print(f"✗ Error reading programs: {e}")
        sys.exit(1)
    print()

    # 3. Get programs matching today's filter (what the scheduler reads)
    print("[3] Reading Programs Matching Today's Filter")
    print("-" * 80)
    try:
        today_programs = lire_programmes_du_jour()
        print(f"Programs for today (YFLGVAL2=1 and today's date): {len(today_programs)}")
        if today_programs:
            print("Programs:")
            for prog in today_programs[:5]:
                print(f"  - {prog['program_code']}: {prog.get('program_type', 'DELIVERY')}")
        else:
            print("✗ NO PROGRAMS FOUND matching today's filter!")
            print()
            print("This explains why nothing is being synced. Check:")
            print("  1. Do the Sage programs have YFLGVAL2_0 = 1?")
            print("  2. Do the Sage programs have today's date?")
            print()
    except Exception as e:
        print(f"✗ Error reading today's programs: {e}")
        print(f"   {e}")
    print()

    # 4. Check database depot mappings
    print("[4] Checking Database Depot Mappings")
    print("-" * 80)
    db = SessionLocal()
    try:
        depots = db.query(Depot).all()
        print(f"Total depots in database: {len(depots)}")
        print()
        print("Depot site codes:")
        for depot in depots:
            print(f"  - {depot.name}: site_code='{depot.site_code}'")

        if depots:
            site_codes = {d.site_code.upper() for d in depots if d.site_code}
            print()
            print(f"Uppercase site codes for matching: {site_codes}")
        print()
    finally:
        db.close()

    # 5. Check for site code mismatches
    print("[5] Checking for Site Code Mismatches")
    print("-" * 80)
    db = SessionLocal()
    try:
        depot_sites = {d.site_code.upper() for d in db.query(Depot).all() if d.site_code}
        sage_sites = {p['site'].upper() for p in all_programs if p['site']}

        matched = sage_sites & depot_sites
        unmatched_sage = sage_sites - depot_sites
        unmatched_db = depot_sites - sage_sites

        print(f"Sage sites that match DB depots: {matched if matched else 'None'}")
        print(f"Sage sites with NO matching depot: {unmatched_sage if unmatched_sage else 'None'}")
        print(f"DB depot sites with NO Sage programs: {unmatched_db if unmatched_db else 'None'}")
        print()

        if unmatched_sage:
            print("⚠ ACTION REQUIRED: Create depots for these Sage sites or fix site codes:")
            for site in unmatched_sage:
                print(f"  - {site}")
        print()
    finally:
        db.close()

    # 6. Check programs already in database
    print("[6] Programs Already in Database")
    print("-" * 80)
    db = SessionLocal()
    try:
        db_programs = db.query(Program).all()
        print(f"Total programs in database: {len(db_programs)}")
        if db_programs:
            print("Recent programs:")
            for prog in sorted(db_programs, key=lambda p: p.created_at, reverse=True)[:5]:
                print(f"  - {prog.program_code}: {prog.status} (created {prog.created_at})")
    finally:
        db.close()
    print()

    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
