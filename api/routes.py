"""FastAPI routes for the trading platform."""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query, Header
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session

from database import get_db
from models import User, BrokerConfig, TelegramChannel, Signal, TradeExecution
from core.credential_manager import CredentialManager
from core.execution_state_manager import SignalExecutor, AuditLogger
from core.signal_parser import SignalParser
from config import load_config
from api.websockets import manager
from api.auth_routes import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["trading"])

# ============ Pydantic Models ============

class BrokerConfigCreate(BaseModel):
    """Create broker configuration."""
    broker_name: str
    login: str
    server: str

class BrokerConfigResponse(BaseModel):
    """Broker configuration response."""
    id: UUID
    broker_name: str
    login: str
    server: str
    created_at: datetime

class CredentialStore(BaseModel):
    """Store a credential."""
    broker_config_id: UUID
    credential_type: str
    credential_value: str

class TelegramChannelCreate(BaseModel):
    """Create Telegram channel."""
    channel_id: int
    channel_name: str

class TelegramChannelResponse(BaseModel):
    """Telegram channel response."""
    id: UUID
    channel_id: int
    channel_name: str
    is_active: bool
    created_at: datetime

class SignalResponse(BaseModel):
    """Trading signal response."""
    id: UUID
    symbol: Optional[str]
    signal_type: Optional[str]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    take_profits: Optional[List[float]] = []
    entry_range: Optional[List[float]] = []
    confidence_score: Optional[float]
    raw_message: str
    status: str
    received_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True

class SubscriberCreate(BaseModel):
    """Create notification subscriber."""
    telegram_id: str
    name: Optional[str] = None

class SubscriberResponse(BaseModel):
    """Subscriber response."""
    id: UUID
    telegram_id: str
    name: Optional[str]
    is_active: bool
    created_at: datetime

class ExecutionResponse(BaseModel):
    """Trade execution response."""
    execution_id: UUID
    signal_id: UUID
    status: str
    symbol: str
    side: str
    ticket: Optional[int]
    entry_price: Optional[float]
    actual_entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    profit_loss: Optional[float]
    executed_at: Optional[datetime]

class TradeModifyRequest(BaseModel):
    """Modify trade request."""
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class ExecuteSignalRequest(BaseModel):
    """Execute signal request."""
    signal_id: UUID
    broker_config_id: UUID

# ============ Broker Configuration Routes ============

@router.post("/broker-configs", response_model=BrokerConfigResponse)
async def create_broker_config(
    config: BrokerConfigCreate,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new broker configuration."""
    try:
        broker_config = BrokerConfig(
            user_id=user_id,
            broker_name=config.broker_name,
            login=config.login,
            server=config.server,
        )
        
        db.add(broker_config)
        db.commit()
        
        logger.info(f"Created broker config for user {user_id}")
        
        return broker_config
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating broker config: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/broker-configs", response_model=List[BrokerConfigResponse])
async def get_broker_configs(
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's broker configurations."""
    try:
        configs = db.query(BrokerConfig).filter(
            BrokerConfig.user_id == user_id
        ).all()
        
        return configs
    except Exception as e:
        logger.error(f"Error getting broker configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/broker-configs/{config_id}")
async def delete_broker_config(
    config_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a broker configuration."""
    try:
        config = db.query(BrokerConfig).filter(
            BrokerConfig.id == config_id,
            BrokerConfig.user_id == user_id,
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="Broker config not found")
        
        db.delete(config)
        db.commit()
        
        logger.info(f"Deleted broker config {config_id}")
        
        return {"status": "deleted"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting broker config: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============ Credential Routes ============

@router.post("/credentials")
async def store_credential(
    credential: CredentialStore,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store an encrypted credential."""
    try:
        credential_manager = CredentialManager()
        
        cred_id = credential_manager.store_credential(
            db,
            user_id,
            credential.credential_type,
            credential.credential_value,
            credential.broker_config_id,
        )
        
        AuditLogger.log_action(
            db,
            user_id,
            "store_credential",
            "credential",
            resource_id=cred_id,
            details={"credential_type": credential.credential_type}
        )
        
        return {"credential_id": cred_id, "status": "stored"}
    except Exception as e:
        logger.error(f"Error storing credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a credential."""
    try:
        credential_manager = CredentialManager()
        
        success = credential_manager.delete_credential(db, credential_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Credential not found")
        
        AuditLogger.log_action(
            db,
            user_id,
            "delete_credential",
            "credential",
            resource_id=credential_id,
        )
        
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Error deleting credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============ Telegram Channel Routes ============

@router.post("/telegram-channels", response_model=TelegramChannelResponse)
async def create_telegram_channel(
    channel: TelegramChannelCreate,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Telegram channel configuration."""
    try:
        telegram_channel = TelegramChannel(
            user_id=user_id,
            channel_id=channel.channel_id,
            channel_name=channel.channel_name,
        )
        
        db.add(telegram_channel)
        db.commit()
        
        logger.info(f"Created Telegram channel for user {user_id}")
        
        return telegram_channel
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating Telegram channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/telegram-channels", response_model=List[TelegramChannelResponse])
async def get_telegram_channels(
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's Telegram channels."""
    try:
        channels = db.query(TelegramChannel).filter(
            TelegramChannel.user_id == user_id
        ).all()
        
        return channels
    except Exception as e:
        logger.error(f"Error getting Telegram channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/telegram-channels/{channel_id}")
async def delete_telegram_channel(
    channel_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a Telegram channel."""
    try:
        channel = db.query(TelegramChannel).filter(
            TelegramChannel.id == channel_id,
            TelegramChannel.user_id == user_id,
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        db.delete(channel)
        db.commit()
        
        logger.info(f"Deleted Telegram channel {channel_id}")
        
        return {"status": "deleted"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting Telegram channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============ Notification Subscriber Routes ============

@router.post("/subscribers", response_model=SubscriberResponse)
async def create_subscriber(
    subscriber: SubscriberCreate,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a notification subscriber."""
    try:
        from models import NotificationSubscriber
        
        sub = NotificationSubscriber(
            user_id=user_id,
            telegram_id=subscriber.telegram_id,
            name=subscriber.name,
        )
        
        db.add(sub)
        db.commit()
        
        logger.info(f"Created subscriber {subscriber.telegram_id} for user {user_id}")
        return sub
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating subscriber: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/subscribers", response_model=List[SubscriberResponse])
async def get_subscribers(
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's subscribers."""
    try:
        from models import NotificationSubscriber
        return db.query(NotificationSubscriber).filter(
            NotificationSubscriber.user_id == user_id
        ).all()
    except Exception as e:
        logger.error(f"Error getting subscribers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/subscribers/{subscriber_id}")
async def delete_subscriber(
    subscriber_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a subscriber."""
    try:
        from models import NotificationSubscriber
        sub = db.query(NotificationSubscriber).filter(
            NotificationSubscriber.id == subscriber_id,
            NotificationSubscriber.user_id == user_id,
        ).first()
        
        if not sub:
            raise HTTPException(status_code=404, detail="Subscriber not found")
            
        db.delete(sub)
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting subscriber: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# System routes moved to main.py for background task management in shared memory.

# ============ Signal Routes ============

@router.get("/signals", response_model=List[SignalResponse])
async def get_signals(
    user_id: UUID = Depends(get_current_user),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get user's trading signals."""
    try:
        signals = db.query(Signal).filter(
            Signal.user_id == user_id
        ).order_by(
            Signal.received_at.desc()
        ).limit(limit).offset(offset).all()
        
        return signals
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/signals/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific signal."""
    try:
        signal = db.query(Signal).filter(
            Signal.id == signal_id,
            Signal.user_id == user_id,
        ).first()
        
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")
        
        return signal
    except Exception as e:
        logger.error(f"Error getting signal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============ Execution Routes ============

@router.post("/executions")
async def execute_signal(
    request: ExecuteSignalRequest,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute a trading signal."""
    try:
        signal = db.query(Signal).filter(
            Signal.id == request.signal_id,
            Signal.user_id == user_id,
        ).first()
        
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")
        
        # Parse signal if not already parsed
        parsed_signal = signal.parsed_data or {}
        
        # Execute signal
        executor = SignalExecutor(db)
        credential_manager = CredentialManager()
        
        # Import here to avoid circular imports
        from core.mt5_executor import MT5Executor
        config = load_config()
        mt5_executor = MT5Executor()
        
        result = await executor.execute_signal(
            request.signal_id,
            request.broker_config_id,
            user_id,
            parsed_signal,
            mt5_executor,
            credential_manager,
        )
        
        AuditLogger.log_action(
            db,
            user_id,
            "execute_signal",
            "signal",
            resource_id=request.signal_id,
            details={"broker_config_id": str(request.broker_config_id), "success": result.get("success")}
        )
        
        return result
    except Exception as e:
        logger.error(f"Error executing signal: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get execution status."""
    try:
        execution = db.query(TradeExecution).filter(
            TradeExecution.id == execution_id,
            TradeExecution.user_id == user_id,
        ).first()
        
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        executor = SignalExecutor(db)
        return executor.get_execution_status(execution_id)
    except Exception as e:
        logger.error(f"Error getting execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/executions", response_model=List[dict])
async def get_executions(
    user_id: UUID = Depends(get_current_user),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get user's trade executions."""
    try:
        executor = SignalExecutor(db)
        return executor.get_user_executions(user_id, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/executions/{execution_id}/close")
async def close_execution(
    execution_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close an open position."""
    try:
        execution = db.query(TradeExecution).filter(
            TradeExecution.id == execution_id,
            TradeExecution.user_id == user_id,
        ).first()
        
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        executor = SignalExecutor(db)
        credential_manager = CredentialManager()
        
        from core.mt5_executor import MT5Executor
        mt5_executor = MT5Executor()
        
        result = await executor.close_position(
            execution_id,
            mt5_executor,
            credential_manager,
            manager,
        )
        
        AuditLogger.log_action(
            db,
            user_id,
            "close_position",
            "execution",
            resource_id=execution_id,
        )
        
        return result
    except Exception as e:
        logger.error(f"Error closing position: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/executions/{execution_id}/modify")
async def modify_execution(
    execution_id: UUID,
    request: TradeModifyRequest,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Modify stop loss and/or take profit."""
    try:
        execution = db.query(TradeExecution).filter(
            TradeExecution.id == execution_id,
            TradeExecution.user_id == user_id,
        ).first()
        
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        credential_manager = CredentialManager()
        
        from core.mt5_executor import MT5Executor
        mt5_executor = MT5Executor()
        
        # Get credentials and broker config
        broker_config = db.query(BrokerConfig).filter(
            BrokerConfig.id == execution.broker_config_id
        ).first()
        
        credentials = credential_manager.get_broker_credentials(
            db,
            user_id,
            execution.broker_config_id,
        )
        
        # Connect and modify
        import asyncio
        await mt5_executor.connect(
            login=int(broker_config.login),
            password=credentials.get("mt5_password"),
            server=broker_config.server,
        )
        
        result = await mt5_executor.modify_position(
            execution.ticket_number,
            request.stop_loss,
            request.take_profit,
        )
        
        if result.get("success"):
            execution.stop_loss = request.stop_loss or execution.stop_loss
            execution.take_profit = request.take_profit or execution.take_profit
            db.commit()
        
        AuditLogger.log_action(
            db,
            user_id,
            "modify_position",
            "execution",
            resource_id=execution_id,
            details={"sl": request.stop_loss, "tp": request.take_profit}
        )
        
        return result
    except Exception as e:
        logger.error(f"Error modifying position: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/executions/{execution_id}/confirm")
async def confirm_execution(
    execution_id: UUID,
    request: TradeModifyRequest, # Reusing this model for optional Entry/SL/TP overrides
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a pending approval execution."""
    try:
        from models import TradeExecution
        from core.execution_state_manager import ExecutionState
        execution = db.query(TradeExecution).filter(
            TradeExecution.id == execution_id,
            TradeExecution.user_id == user_id,
        ).first()
        
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        if execution.execution_status not in ["pending_approval", "failed"]:
             raise HTTPException(status_code=400, detail=f"Execution is in {execution.execution_status} state, not pending_approval or failed")

        # Update values if provided
        if request.stop_loss is not None:
            execution.stop_loss = request.stop_loss
        if request.take_profit is not None:
            execution.take_profit = request.take_profit
        # Note: Entry price update might be needed too. Let's assume TradeModifyRequest has it or we add it. 
        # For now, we only update SL/TP from the request model available. 
        # If we need entry price, we should update the model. 
        # Let's check TradeModifyRequest... it only has sl/tp. 
        # We can dynamically get it from body if needed or generic dict. 
        # But let's proceed with SL/TP overrides for now.

        db.commit()
 
        # Build signal-like dict for overrides
        signal_data = {
            "symbol": execution.symbol,
            "signal_type": execution.side,
            "entry_price": execution.entry_price, # Original entry
            "stop_loss": execution.stop_loss,
            "take_profit": execution.take_profit,
            "confidence_score": 1.0, # Manual approval always counts as highly confident
        }

        # Trigger Execution
        executor = SignalExecutor(db)
        credential_manager = CredentialManager()
        from core.mt5_executor import MT5Executor
        config = load_config()
        mt5_executor = MT5Executor()
 
        result = await executor.execute_signal(
            signal_id=execution.signal_id,
            broker_config_id=execution.broker_config_id,
            user_id=user_id,
            parsed_signal=signal_data,
            mt5_executor=mt5_executor,
            credential_manager=credential_manager,
            execution_id=execution_id # RESUME!
        )
        
        if not result.get("success"):
             raise HTTPException(status_code=400, detail=result.get("error"))
             
        return result

    except Exception as e:
        logger.error(f"Error confirming execution: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending signal approval."""
    try:
        executor = SignalExecutor(db)
        result = await executor.reject_execution(execution_id)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error"))
            
        return result
    except Exception as e:
        logger.error(f"Error rejecting execution: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============ Settings Routes ============

class SettingsUpdate(BaseModel):
    manual_approval: Optional[bool] = None
    risk_per_trade: Optional[float] = None
    max_slippage: Optional[float] = None
    default_stop_loss_pips: Optional[int] = None
    use_limit_orders: Optional[bool] = None

@router.get("/settings")
async def get_settings(
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user settings."""
    from models import UserPreferences
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs:
        # Create default
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs

@router.put("/settings")
async def update_settings(
    settings: SettingsUpdate,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user settings."""
    from models import UserPreferences
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
    
    if settings.manual_approval is not None:
        prefs.manual_approval = settings.manual_approval
    if settings.risk_per_trade is not None:
        prefs.risk_per_trade = settings.risk_per_trade
    if settings.max_slippage is not None:
        prefs.max_slippage = settings.max_slippage
    if settings.default_stop_loss_pips is not None:
        prefs.default_stop_loss_pips = settings.default_stop_loss_pips
    if settings.use_limit_orders is not None:
        prefs.use_limit_orders = settings.use_limit_orders
        
    db.commit()
    db.refresh(prefs)
    return prefs

# ============ Account Routes ============

@router.get("/account/info")
async def get_account_info(
    broker_config_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get MT5 account information."""
    try:
        broker_config = db.query(BrokerConfig).filter(
            BrokerConfig.id == broker_config_id,
            BrokerConfig.user_id == user_id,
        ).first()
        
        if not broker_config:
            raise HTTPException(status_code=404, detail="Broker config not found")
        
        credential_manager = CredentialManager()
        credentials = credential_manager.get_broker_credentials(
            db,
            user_id,
            broker_config_id,
        )
        
        from core.mt5_executor import MT5Executor
        mt5_executor = MT5Executor()
        
        import asyncio
        await mt5_executor.connect(
            login=int(broker_config.login),
            password=credentials.get("mt5_password"),
            server=broker_config.server,
        )
        
        return mt5_executor.get_account_info()
    except Exception as e:
        logger.error(f"Error getting account info: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============ Health Check ============

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
