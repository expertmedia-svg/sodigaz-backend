import sqlite3

conn = sqlite3.connect('dev.db')
cursor = conn.cursor()

print("=== USERS (ravitailleurs) ===")
cursor.execute('SELECT id, email, username, full_name, role, is_active FROM users WHERE role = "ravitailleur"')
for row in cursor.fetchall():
    print(f"User ID: {row[0]}, Email: {row[1]}, Username: {row[2]}, Name: {row[3]}, Active: {row[5]}")

print("\n=== DRIVER MAPPINGS ===")
cursor.execute('SELECT id, user_id, sage_driver_code, truck_code, is_active, status FROM driver_mappings')
for row in cursor.fetchall():
    print(f"Mapping ID: {row[0]}, User ID: {row[1]}, Sage Code: {row[2]}, Truck: {row[3]}, Active: {row[4]}, Status: {row[5]}")

print("\n=== PROGRAMS ===")
cursor.execute('SELECT id, program_code, driver_id, yliv, ymatcam, status FROM programs LIMIT 10')
for row in cursor.fetchall():
    print(f"Program ID: {row[0]}, Code: {row[1]}, Driver ID: {row[2]}, YLIV: {row[3]}, YMATCAM: {row[4]}, Status: {row[5]}")

print("\n=== DELIVERIES ===")
cursor.execute('SELECT id, program_id, driver_id, destination_name, status, source_type, quantity_6kg, quantity_12kg FROM deliveries LIMIT 10')
for row in cursor.fetchall():
    print(f"Delivery ID: {row[0]}, Program ID: {row[1]}, Driver ID: {row[2]}, Dest: {row[3]}, Status: {row[4]}, Source: {row[5]}, Q6: {row[6]}, Q12: {row[7]}")

conn.close()
