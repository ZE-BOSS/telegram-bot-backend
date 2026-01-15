import os
import sys
from sqlalchemy import create_engine, text

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config

def migrate():
    config = load_config()
    engine = create_engine(config.database.url)
    
    with engine.connect() as conn:
        try:
            print("Adding status column to signals table...")
            conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending'"))
            conn.commit()
            print("Migration successful.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
