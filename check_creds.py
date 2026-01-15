import os
import sys
from uuid import UUID
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config

def check_creds():
    config = load_config()
    engine = create_engine(config.database.url)
    
    with engine.connect() as conn:
        print("--- Checking Encrypted Credentials ---")
        result = conn.execute(text("SELECT id, user_id, credential_type, broker_config_id FROM encrypted_credentials"))
        rows = result.fetchall()
        if not rows:
            print("No credentials found in database.")
        else:
            for row in rows:
                print(f"ID: {row[0]}, User: {row[1]}, Type: {row[2]}, BrokerConfig: {row[3]}")
        
        print("\n--- Checking Broker Configs ---")
        result = conn.execute(text("SELECT id, name, login, server FROM broker_configs"))
        rows = result.fetchall()
        for row in rows:
            print(f"ID: {row[0]}, Name: {row[1]}, Login: {row[2]}, Server: {row[3]}")

if __name__ == "__main__":
    check_creds()
