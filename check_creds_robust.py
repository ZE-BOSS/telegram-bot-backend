import os
import sys
from sqlalchemy import create_engine, text

# Properly setup path
base_dir = r"c:\Users\ikchr\Music\telegram-bot"
if base_dir not in sys.path:
    sys.path.append(base_dir)

from config import load_config

def check_creds():
    try:
        config = load_config()
        print(f"Connecting to: {config.database.url.split('@')[-1]}") # Print host/db only
        engine = create_engine(config.database.url)
        
        with engine.connect() as conn:
            print("\n--- Credential Counts ---")
            for c_type in ['mt5_password', 'api_key']:
                res = conn.execute(text(f"SELECT count(*) FROM encrypted_credentials WHERE credential_type = '{c_type}'"))
                count = res.fetchone()[0]
                print(f"{c_type}: {count}")
            
            print("\n--- Broker Configs ---")
            res = conn.execute(text("SELECT id, broker_name, login, server FROM broker_configs"))
            for row in res:
                print(f"ID: {row[0]}, Name: {row[1]}, Login: {row[2]}, Server: {row[3]}")
                
            print("\n--- Recent Executions ---")
            res = conn.execute(text("SELECT id, execution_status, execution_error FROM trade_executions ORDER BY created_at DESC LIMIT 5"))
            for row in res:
                print(f"ID: {row[0]}, Status: {row[1]}, Error: {row[2]}")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    check_creds()
