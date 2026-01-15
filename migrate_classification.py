"""Add message classification fields to signals table."""
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "backend"))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def run_migration():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment")
        return
    
    engine = create_engine(database_url)
    
    print("Adding message classification columns to signals table...")
    
    with engine.connect() as conn:
        # Add columns if they don't exist
        try:
            conn.execute(text("""
                ALTER TABLE signals 
                ADD COLUMN IF NOT EXISTS message_category VARCHAR,
                ADD COLUMN IF NOT EXISTS modification_type VARCHAR,
                ADD COLUMN IF NOT EXISTS is_actionable BOOLEAN DEFAULT TRUE;
            """))
            conn.commit()
            print("✓ Successfully added columns")
        except Exception as e:
            print(f"✗ Error adding columns: {e}")
            conn.rollback()
            return
        
        # Update existing records to have default values
        try:
            conn.execute(text("""
                UPDATE signals 
                SET message_category = 'actionable_signal',
                    is_actionable = TRUE
                WHERE message_category IS NULL;
            """))
            conn.commit()
            print("✓ Updated existing records with default values")
        except Exception as e:
            print(f"✗ Error updating records: {e}")
            conn.rollback()
    
    print("\nMigration completed successfully!")

if __name__ == "__main__":
    run_migration()
