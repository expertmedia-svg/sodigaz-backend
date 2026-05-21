import sqlite3

conn = sqlite3.connect('dev.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM programs')
programs = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM deliveries')
deliveries = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM users WHERE role = "ravitailleur"')
ravitailleurs = cursor.fetchone()[0]

print(f'Programs: {programs}')
print(f'Deliveries: {deliveries}')
print(f'Ravitailleur users: {ravitailleurs}')

# Check a sample delivery
if deliveries > 0:
    cursor.execute('SELECT id, program_id, program_line_id, driver_id, status FROM deliveries LIMIT 3')
    for row in cursor.fetchall():
        print(f'  Delivery {row[0]}: program_id={row[1]}, program_line_id={row[2]}, driver_id={row[3]}, status={row[4]}')

conn.close()
