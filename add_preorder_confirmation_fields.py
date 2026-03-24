"""Add confirmed_at and confirmed_by_id to preorders table"""

from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:///./dev.db"
engine = create_engine(DATABASE_URL)

with engine.connect() as connection:
    # Add confirmed_at column
    try:
        connection.execute(text("ALTER TABLE preorders ADD COLUMN confirmed_at DATETIME"))
        connection.commit()
        print("✓ Added confirmed_at column")
    except Exception as e:
        print(f"confirmed_at column might already exist: {e}")
    
    # Add confirmed_by_id column
    try:
        connection.execute(text("ALTER TABLE preorders ADD COLUMN confirmed_by_id INTEGER REFERENCES users(id)"))
        connection.commit()
        print("✓ Added confirmed_by_id column")
    except Exception as e:
        print(f"confirmed_by_id column might already exist: {e}")

print("\nMigration complete!")
