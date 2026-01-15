"""Database models using SQLAlchemy."""
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, Numeric, ForeignKey, BigInteger, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from uuid import UUID, uuid4
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class User(Base):
    """User account."""
    __tablename__ = "users"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    username = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    broker_configs = relationship("BrokerConfig", back_populates="user", cascade="all, delete-orphan")
    credentials = relationship("EncryptedCredential", back_populates="user", cascade="all, delete-orphan")
    telegram_channels = relationship("TelegramChannel", back_populates="user", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="user", cascade="all, delete-orphan")
    trade_executions = relationship("TradeExecution", back_populates="user", cascade="all, delete-orphan")
    notification_subscribers = relationship("NotificationSubscriber", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")


class BrokerConfig(Base):
    """Broker configuration per user."""
    __tablename__ = "broker_configs"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    broker_name = Column(String, nullable=False)
    login = Column(String, nullable=False)
    server = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="broker_configs")
    credentials = relationship("EncryptedCredential", back_populates="broker_config", cascade="all, delete-orphan")
    trade_executions = relationship("TradeExecution", back_populates="broker_config", cascade="all, delete-orphan")


class EncryptedCredential(Base):
    """Encrypted credential storage."""
    __tablename__ = "encrypted_credentials"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    credential_type = Column(String, nullable=False)  # 'mt5_password', 'api_key', etc.
    broker_config_id = Column(sa.UUID, ForeignKey("broker_configs.id"), nullable=True)
    encrypted_value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="credentials")
    broker_config = relationship("BrokerConfig", back_populates="credentials")


class TelegramChannel(Base):
    """Telegram channel configuration."""
    __tablename__ = "telegram_channels"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    channel_id = Column(BigInteger, nullable=False)
    channel_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="telegram_channels")
    signals = relationship("Signal", back_populates="telegram_channel", cascade="all, delete-orphan")


class Signal(Base):
    """Trading signal from Telegram."""
    __tablename__ = "signals"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    telegram_channel_id = Column(sa.UUID, ForeignKey("telegram_channels.id"), nullable=False, index=True)
    raw_message = Column(Text, nullable=False)
    parsed_data = Column(JSONB, nullable=True)
    signal_type = Column(String, nullable=True)  # 'buy', 'sell', 'close', 'modify'
    symbol = Column(String, nullable=True)
    entry_price = Column(Numeric, nullable=True)
    stop_loss = Column(Numeric, nullable=True)
    take_profit = Column(Numeric, nullable=True)
    confidence_score = Column(Numeric, nullable=True)  # 0-1
    message_category = Column(String, nullable=True)  # 'actionable_signal', 'modification', 'commentary'
    modification_type = Column(String, nullable=True)  # 'breakeven_move', 'cancellation', etc.
    is_actionable = Column(Boolean, default=True)  # Computed from message_category
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)
    status = Column(String, default="pending")  # 'pending', 'processed', 'rejected'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="signals")
    telegram_channel = relationship("TelegramChannel", back_populates="signals")
    trade_executions = relationship("TradeExecution", back_populates="signal", cascade="all, delete-orphan")

    @property
    def take_profits(self):
        """Extract multi-TP from parsed_data JSON."""
        return self.parsed_data.get("take_profits", []) if self.parsed_data else []

    @property
    def entry_range(self):
        """Extract entry range from parsed_data JSON."""
        return self.parsed_data.get("entry_range", []) if self.parsed_data else []


class TradeExecution(Base):
    """Trade execution record."""
    __tablename__ = "trade_executions"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    signal_id = Column(sa.UUID, ForeignKey("signals.id"), nullable=False, index=True)
    broker_config_id = Column(sa.UUID, ForeignKey("broker_configs.id"), nullable=False)
    order_id = Column(String, nullable=True)
    ticket_number = Column(BigInteger, nullable=True)
    execution_status = Column(String, nullable=False)  # 'pending', 'executed', 'failed'
    execution_type = Column(String, nullable=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # 'buy', 'sell'
    volume = Column(Numeric, nullable=False)
    entry_price = Column(Numeric, nullable=True)
    stop_loss = Column(Numeric, nullable=True)
    take_profit = Column(Numeric, nullable=True)
    actual_entry_price = Column(Numeric, nullable=True)
    actual_entry_time = Column(DateTime, nullable=True)
    close_price = Column(Numeric, nullable=True)
    close_time = Column(DateTime, nullable=True)
    profit_loss = Column(Numeric, nullable=True)
    execution_error = Column(Text, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="trade_executions")
    signal = relationship("Signal", back_populates="trade_executions")
    broker_config = relationship("BrokerConfig", back_populates="trade_executions")


class NotificationSubscriber(Base):
    """Subscriber for signal notifications."""
    __tablename__ = "notification_subscribers"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, index=True)
    telegram_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="notification_subscribers")


class UserPreferences(Base):
    """User trading preferences."""
    __tablename__ = "user_preferences"
    
    id = Column(sa.UUID, primary_key=True, default=uuid4)
    user_id = Column(sa.UUID, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    manual_approval = Column(Boolean, default=True)  # Require manual review before execution
    risk_per_trade = Column(Numeric, default=1.0)  # % of equity
    max_slippage = Column(Numeric, default=5.0)  # pip s
    default_stop_loss_pips = Column(Integer, default=20)
    use_limit_orders = Column(Boolean, default=True) # Use limit orders if price gap
    max_open_positions = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="preferences")


# Add relationship to User class (we need to inject it or modify User class above)
# Ideally we modify the User class, but since we are appending, we can use dependency injection if possible 
# or just assume the User class already has it if we modify it in a separate call.
# Actually, let's just add it to the file at once if possible.
# Wait, I cannot modify the User class earlier in the file easily with append. 
# But python allows late binding if using string names in relationship.
# So I should modify User class to add the relationship.

