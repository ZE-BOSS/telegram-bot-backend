import os
import sys
import uuid
import json
from sqlalchemy.orm import Session

# Setup path
base_dir = r"c:\Users\ikchr\Music\telegram-bot"
if base_dir not in sys.path:
    sys.path.append(base_dir)

from database import SessionLocal
from models import BrokerConfig, User
from core.credential_manager import CredentialManager

def verify_cred_fix():
    db = SessionLocal()
    try:
        # Get first user and broker
        user = db.query(User).first()
        broker = db.query(BrokerConfig).filter(BrokerConfig.user_id == user.id).first()
        
        if not user or not broker:
            print("Setup incomplete: User or Broker missing.")
            return

        print(f"Testing for User: {user.username}, Broker: {broker.broker_name}")
        
        manager = CredentialManager()
        
        # Test Storage
        cred_id = manager.store_credential(
            db, 
            user.id, 
            "mt5_password", 
            "test_pass_123", 
            broker.id
        )
        print(f"Stored credential ID: {cred_id}")
        
        # Test Retrieval
        creds = manager.get_broker_credentials(db, user.id, broker.id)
        if creds.get("mt5_password") == "test_pass_123":
            print("SUCCESS: Credential stored and retrieved correctly.")
        else:
            print(f"FAILURE: Retrieved wrong value: {creds.get('mt5_password')}")

        # Test Upsert
        manager.store_credential(
            db, 
            user.id, 
            "mt5_password", 
            "new_pass_456", 
            broker.id
        )
        creds_updated = manager.get_broker_credentials(db, user.id, broker.id)
        if creds_updated.get("mt5_password") == "new_pass_456":
            print("SUCCESS: Credential updated correctly (Upsert).")
        else:
            print(f"FAILURE: Upsert failed. Value: {creds_updated.get('mt5_password')}")

    finally:
        db.close()

if __name__ == "__main__":
    verify_cred_fix()
