"""Background manager for syncing MT5 status."""
import asyncio
import logging
from datetime import datetime
from uuid import UUID
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from core.execution_state_manager import ExecutionState, SignalExecutor
from core.mt5_executor import MT5Executor
from core.credential_manager import CredentialManager
from models import TradeExecution, BrokerConfig, UserPreferences
from api.websockets import manager
from config import load_config

logger = logging.getLogger(__name__)

class PositionSyncManager:
    """Synchronizes MT5 positions with the database."""
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
        config = load_config()
        self.mt5_executor = MT5Executor(mt5_path=config.mt5.mt5_path)
        self.credential_manager = CredentialManager()
        self.is_running = False
        self._task = None

    async def start(self):
        """Start the sync background task."""
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("PositionSyncManager started")

    async def stop(self):
        """Stop the sync background task."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PositionSyncManager stopped")

    async def _sync_loop(self):
        """Main loop for position synchronization."""
        while self.is_running:
            try:
                await self.sync_all_active_positions()
            except Exception as e:
                logger.error(f"Error in sync loop: {e}", exc_info=True)
            
            await asyncio.sleep(5)  # Sync every 5 seconds

    async def sync_all_active_positions(self):
        """Sync positions for all users with active trades."""
        db = self.session_factory()
        try:
            # Find all users who have active (EXECUTED) trades
            active_executions = db.query(TradeExecution).filter(
                TradeExecution.execution_status == ExecutionState.EXECUTED.value
            ).all()

            if not active_executions:
                return

            # Group by broker config to avoid redundant connections
            by_broker = {}
            for ex in active_executions:
                if ex.broker_config_id not in by_broker:
                    by_broker[ex.broker_config_id] = []
                by_broker[ex.broker_config_id].append(ex)

            for broker_id, items in by_broker.items():
                await self._sync_broker_positions(db, broker_id, items)

        finally:
            db.close()

    async def _sync_broker_positions(self, db: Session, broker_id: UUID, executions: List[TradeExecution]):
        """Sync positions for a specific broker account."""
        try:
            user_id = executions[0].user_id
            broker_config = db.query(BrokerConfig).filter(BrokerConfig.id == broker_id).first()
            if not broker_config:
                return

            credentials = self.credential_manager.get_broker_credentials(db, user_id, broker_id)
            if not credentials.get("mt5_password"):
                return

            # Connect to MT5
            connected = await self.mt5_executor.connect(
                login=int(broker_config.login),
                password=credentials.get("mt5_password"),
                server=broker_config.server,
            )
            
            if not connected:
                return

            # Get all open positions from MT5
            mt5_positions = self.mt5_executor.get_positions()
            mt5_tickets = {p["ticket"]: p for p in mt5_positions}

            for ex in executions:
                if not ex.ticket_number:
                    continue

                if ex.ticket_number in mt5_tickets:
                    # Position is still open
                    p = mt5_tickets[ex.ticket_number]
                    ex.profit_loss = p["profit"]
                    db.commit()
                    
                    # Broadcast live P/L update
                    await manager.broadcast({
                        "type": "position_update",
                        "execution_id": str(ex.id),
                        "profit_loss": float(ex.profit_loss),
                        "price_current": float(p["price_current"])
                    }, user_id=user_id)
                else:
                    # Position might be closed
                    logger.info(f"Position {ex.ticket_number} not found in MT5, checking history...")
                    deal = self.mt5_executor.get_history_deals(int(ex.ticket_number))
                    if deal:
                        ex.execution_status = ExecutionState.CLOSED.value
                        ex.profit_loss = deal["profit"]
                        ex.close_price = deal["price"]
                        ex.close_time = datetime.fromisoformat(deal["time"]) if isinstance(deal["time"], str) else deal["time"]
                        db.commit()
                        
                        # Broadcast closure
                        await manager.broadcast({
                            "type": "position_closed",
                            "execution_id": str(ex.id),
                            "profit_loss": float(ex.profit_loss),
                            "close_price": float(ex.close_price)
                        }, user_id=user_id)
                    else:
                        # Cannot find position or deal, maybe failed? 
                        # We don't want to mark it failed immediately in case of sync issues
                        pass

        except Exception as e:
            logger.error(f"Error syncing broker {broker_id}: {e}")
