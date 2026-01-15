"""Secure credential management with encryption."""
import logging
import os
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import json
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from models import EncryptedCredential, BrokerConfig

logger = logging.getLogger(__name__)

class CredentialManager:
    """Secure credential management with encryption."""
    
    def __init__(self, master_key: Optional[str] = None):
        """Initialize credential manager."""
        self.master_key = master_key or os.getenv("MASTER_ENCRYPTION_KEY")
        if not self.master_key:
            raise ValueError("MASTER_ENCRYPTION_KEY environment variable not set")
        
        if len(self.master_key) < 32:
            raise ValueError("MASTER_ENCRYPTION_KEY must be at least 32 characters")
        
        self.cipher = self._init_cipher()
    
    def _init_cipher(self) -> Fernet:
        """Initialize Fernet cipher with master key."""
        try:
            # Derive key from master key using PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b'trading-platform-salt',
                iterations=100000,
                backend=default_backend(),
            )
            key = base64.urlsafe_b64encode(
                kdf.derive(self.master_key.encode())
            )
            return Fernet(key)
        except Exception as e:
            logger.error(f"Error initializing cipher: {e}")
            raise
    
    def encrypt_credential(self, credential_value: str) -> str:
        """
        Encrypt a credential value.
        
        Args:
            credential_value: The value to encrypt
            
        Returns:
            Encrypted value as string
        """
        try:
            encrypted = self.cipher.encrypt(credential_value.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Error encrypting credential: {e}")
            raise
    
    def decrypt_credential(self, encrypted_value: str) -> str:
        """
        Decrypt a credential value.
        
        Args:
            encrypted_value: The encrypted value to decrypt
            
        Returns:
            Decrypted value as string
        """
        try:
            decrypted = self.cipher.decrypt(encrypted_value.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Error decrypting credential: {e}")
            raise
    
    def store_credential(
        self,
        db_session: Session,
        user_id: UUID,
        credential_type: str,
        credential_value: str,
        broker_config_id: Optional[UUID] = None,
    ) -> Optional[UUID]:
        """
        Store an encrypted credential in database.
        
        Args:
            db_session: Database session
            user_id: User ID
            credential_type: Type of credential (e.g., 'mt5_password', 'api_key')
            credential_value: The credential value to encrypt and store
            broker_config_id: Optional broker config association
            
        Returns:
            Credential ID or None if failed
        """
        try:
            # Encrypt the value
            encrypted = self.encrypt_credential(credential_value)
            
            # Check if credential already exists for this user/broker/type
            existing_cred = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.user_id == user_id,
                EncryptedCredential.broker_config_id == broker_config_id,
                EncryptedCredential.credential_type == credential_type
            ).first()
            
            if existing_cred:
                existing_cred.encrypted_value = encrypted
                existing_cred.updated_at = datetime.utcnow()
                cred = existing_cred
                logger.info(f"Updated existing credential {credential_type} for user {user_id}")
            else:
                # Create new credential record
                cred = EncryptedCredential(
                    user_id=user_id,
                    credential_type=credential_type,
                    broker_config_id=broker_config_id,
                    encrypted_value=encrypted,
                )
                db_session.add(cred)
                logger.info(f"Stored new credential {credential_type} for user {user_id}")
            
            db_session.commit()
            return cred.id
        except Exception as e:
            logger.error(f"Error storing credential: {e}")
            db_session.rollback()
            raise
    
    def retrieve_credential(
        self,
        db_session: Session,
        credential_id: UUID,
    ) -> Optional[str]:
        """
        Retrieve and decrypt a credential.
        
        Args:
            db_session: Database session
            credential_id: Credential ID
            
        Returns:
            Decrypted credential value or None
        """
        try:
            cred = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.id == credential_id
            ).first()
            
            if not cred:
                logger.warning(f"Credential not found: {credential_id}")
                return None
            
            # Decrypt and return
            decrypted = self.decrypt_credential(cred.encrypted_value)
            return decrypted
        except Exception as e:
            logger.error(f"Error retrieving credential: {e}")
            return None
    
    def get_broker_credentials(
        self,
        db_session: Session,
        user_id: UUID,
        broker_config_id: UUID,
    ) -> dict:
        """
        Get all credentials for a broker configuration.
        
        Args:
            db_session: Database session
            user_id: User ID
            broker_config_id: Broker config ID
            
        Returns:
            Dict with credential types as keys and decrypted values
        """
        try:
            creds = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.user_id == user_id,
                EncryptedCredential.broker_config_id == broker_config_id,
            ).all()
            
            result = {}
            for cred in creds:
                try:
                    result[cred.credential_type] = self.decrypt_credential(cred.encrypted_value)
                except Exception as e:
                    logger.error(f"Error decrypting credential {cred.id}: {e}")
            
            return result
        except Exception as e:
            logger.error(f"Error getting broker credentials: {e}")
            return {}
    
    def update_credential(
        self,
        db_session: Session,
        credential_id: UUID,
        new_value: str,
    ) -> bool:
        """
        Update an encrypted credential.
        
        Args:
            db_session: Database session
            credential_id: Credential ID
            new_value: New credential value
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cred = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.id == credential_id
            ).first()
            
            if not cred:
                logger.warning(f"Credential not found: {credential_id}")
                return False
            
            # Encrypt and update
            cred.encrypted_value = self.encrypt_credential(new_value)
            cred.updated_at = datetime.utcnow()
            
            db_session.commit()
            logger.info(f"Updated credential {credential_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating credential: {e}")
            db_session.rollback()
            return False
    
    def delete_credential(
        self,
        db_session: Session,
        credential_id: UUID,
    ) -> bool:
        """
        Delete a credential.
        
        Args:
            db_session: Database session
            credential_id: Credential ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cred = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.id == credential_id
            ).first()
            
            if not cred:
                logger.warning(f"Credential not found: {credential_id}")
                return False
            
            db_session.delete(cred)
            db_session.commit()
            logger.info(f"Deleted credential {credential_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting credential: {e}")
            db_session.rollback()
            return False
    
    def validate_mt5_credential(
        self,
        db_session: Session,
        user_id: UUID,
        broker_config_id: UUID,
    ) -> bool:
        """
        Validate that all required MT5 credentials are present.
        
        Args:
            db_session: Database session
            user_id: User ID
            broker_config_id: Broker config ID
            
        Returns:
            True if all required credentials are present
        """
        required_creds = ['mt5_password']
        
        try:
            creds = db_session.query(EncryptedCredential).filter(
                EncryptedCredential.user_id == user_id,
                EncryptedCredential.broker_config_id == broker_config_id,
            ).all()
            
            cred_types = {cred.credential_type for cred in creds}
            return all(req in cred_types for req in required_creds)
        except Exception as e:
            logger.error(f"Error validating MT5 credentials: {e}")
            return False


class CredentialRotation:
    """Handle credential rotation for security."""
    
    def __init__(self, credential_manager: CredentialManager):
        """Initialize credential rotation."""
        self.manager = credential_manager
    
    def rotate_master_key(
        self,
        db_session: Session,
        old_key: str,
        new_key: str,
    ) -> bool:
        """
        Rotate the master encryption key by re-encrypting all credentials.
        
        Args:
            db_session: Database session
            old_key: Old master key
            new_key: New master key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Starting master key rotation...")
            
            # Create manager with old key
            old_manager = CredentialManager(old_key)
            
            # Get all credentials
            all_creds = db_session.query(EncryptedCredential).all()
            
            # Re-encrypt with new key
            for cred in all_creds:
                try:
                    # Decrypt with old key
                    decrypted = old_manager.decrypt_credential(cred.encrypted_value)
                    
                    # Encrypt with new manager (which uses new key)
                    self.manager = CredentialManager(new_key)
                    cred.encrypted_value = self.manager.encrypt_credential(decrypted)
                    
                except Exception as e:
                    logger.error(f"Error rotating credential {cred.id}: {e}")
                    return False
            
            db_session.commit()
            logger.info("Master key rotation completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during master key rotation: {e}")
            db_session.rollback()
            return False
