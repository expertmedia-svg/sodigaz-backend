import sqlite3

conn = sqlite3.connect('dev.db')
cursor = conn.cursor()

# Get recent programs (last 5)
cursor.execute('''
    SELECT id, program_code, yliv, ymatcam, status, created_at
    FROM programs
    ORDER BY created_at DESC
    LIMIT 5
''')

print("Recent programs:")
print("-" * 100)
for row in cursor.fetchall():
    print(f"ID: {row[0]}, Code: {row[1]}, YLIV: {row[2]}, YMATCAM: {row[3]}, Status: {row[4]}, Created: {row[5]}")

conn.close()
