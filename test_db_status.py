import os
import sys
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config

def test_status_col():
    config = load_config()
    engine = create_engine(config.database.url)
    
    with engine.connect() as conn:
        try:
            print(f"Executing: SELECT status FROM signals LIMIT 1")
            result = conn.execute(text("SELECT status FROM signals LIMIT 1"))
            row = result.fetchone()
            print(f"Result: {row}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_status_col()
