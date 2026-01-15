import os
import sys
from sqlalchemy import create_engine, inspect

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config

def check_schema():
    config = load_config()
    engine = create_engine(config.database.url)
    inspector = inspect(engine)
    
    tables = inspector.get_table_names()
    print(f"Tables found: {tables}")
    
    for table in tables:
        print(f"\nChecking table: {table}")
        columns = inspector.get_columns(table)
        for column in columns:
            print(f"Column: {column['name']}, Type: {column['type']}")

if __name__ == "__main__":
    check_schema()
