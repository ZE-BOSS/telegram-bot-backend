"""State management and execution tracking for trading signals."""
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import and_

logger = logging.getLogger(__name__)

class ExecutionState(str, Enum):
    """Trade execution states."""
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    VALIDATED = "validated"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLOSED = "closed"

class SignalExecutor:
    """Manages signal execution lifecycle and state tracking."""
    
    def __init__(self, db_session: Session):
        """Initialize signal executor."""
        self.db_session = db_session
        self.active_executions: Dict[UUID, Dict[str, Any]] = {}
    
    async def execute_signal(
        self,
        signal_id: UUID,
        broker_config_id: UUID,
        user_id: UUID,
        parsed_signal: Dict[str, Any],
        mt5_executor,
        credential_manager,
        execution_id: Optional[UUID] = None, # Added to support resuming
    ) -> Dict[str, Any]:
        """
        Execute a trading signal end-to-end.
        
        Returns execution result with ticket number and status
        """
        try:
            from models import TradeExecution, Signal, BrokerConfig, UserPreferences
            from api.websockets import manager
            
            logger.info(f"Starting execution for signal {signal_id}")
            
            # Get signal and broker config
            signal = self.db_session.query(Signal).filter(Signal.id == signal_id).first()
            broker_config = self.db_session.query(BrokerConfig).filter(
                BrokerConfig.id == broker_config_id
            ).first()
            user_prefs = self.db_session.query(UserPreferences).filter(
                UserPreferences.user_id == user_id
            ).first()
            
            if not signal or not broker_config:
                return {
                    "success": False,
                    "error": "Signal or broker config not found",
                    "execution_id": None,
                }
            
            # Determine Take Profits list
            tps = parsed_signal.get("take_profits", [])
            if not tps and parsed_signal.get("take_profit"):
                tps = [parsed_signal.get("take_profit")]
            if not tps:
                tps = [None] # At least one position with no TP if none provided
            
            # Volume splitting (Assume 1.0 total for now, split among TPs)
            # We should probably get this from user_prefs. risk_per_trade or something?
            # For now, default to 0.1 per position or split 1.0
            total_volume = float(user_prefs.risk_per_trade) if user_prefs and user_prefs.risk_per_trade else 1.0
            pos_volume = round(total_volume / len(tps), 2)
            if pos_volume < 0.01: pos_volume = 0.01

            # Manual Approval Check (Only if not already an existing execution being resumed)
            if not execution_id and user_prefs and user_prefs.manual_approval:
                # Basic validation
                if not self._validate_signal(parsed_signal):
                     return {"success": False, "error": "Validation failed", "execution_id": None}

                created_ids = []
                for tp in tps:
                    execution = TradeExecution(
                        user_id=user_id,
                        signal_id=signal_id,
                        broker_config_id=broker_config_id,
                        symbol=parsed_signal.get("symbol"),
                        side=parsed_signal.get("signal_type"),
                        volume=pos_volume, 
                        entry_price=parsed_signal.get("entry_price"),
                        stop_loss=parsed_signal.get("stop_loss"),
                        take_profit=tp,
                        execution_status=ExecutionState.PENDING_APPROVAL.value,
                    )
                    self.db_session.add(execution)
                    self.db_session.flush() # Get ID
                    
                    # Broadcast WS event for this specific position
                    await manager.broadcast({
                        "type": "signal_approval_required",
                        "signal_id": str(signal_id),
                        "execution_id": str(execution.id),
                        "symbol": execution.symbol,
                        "side": execution.side,
                        "entry_price": float(execution.entry_price) if execution.entry_price else None,
                        "stop_loss": float(execution.stop_loss) if execution.stop_loss else None,
                        "take_profit": float(execution.take_profit) if execution.take_profit else None,
                    }, user_id=user_id)
                    
                    created_ids.append(execution.id)
                
                self.db_session.commit()
                
                return {
                    "success": True, 
                    "status": "pending_approval", 
                    "execution_ids": [str(eid) for eid in created_ids]
                }


            # --- Continue with Execution (either new or resumed) ---
            
            if execution_id:
                # Resuming a single specific position
                execution = self.db_session.query(TradeExecution).filter(TradeExecution.id == execution_id).first()
                if not execution:
                    raise ValueError(f"Execution {execution_id} not found")
                
                # Update with current parsed signal (might have overrides)
                execution.entry_price = parsed_signal.get("entry_price")
                execution.stop_loss = parsed_signal.get("stop_loss")
                execution.take_profit = parsed_signal.get("take_profit")
                self.db_session.commit()
                
                # Process single execution
                return await self._process_single_execution(
                    execution, parsed_signal, mt5_executor, user_prefs, credential_manager, manager
                )
            else:
                 # Auto-execute: Process all TPs as separate executions
                results = []
                for tp in tps:
                    execution = TradeExecution(
                        user_id=user_id,
                        signal_id=signal_id,
                        broker_config_id=broker_config_id,
                        symbol=parsed_signal.get("symbol"),
                        side=parsed_signal.get("signal_type"),
                        volume=pos_volume, 
                        entry_price=parsed_signal.get("entry_price"),
                        stop_loss=parsed_signal.get("stop_loss"),
                        take_profit=tp,
                        execution_status=ExecutionState.PENDING.value,
                    )
                    self.db_session.add(execution)
                    self.db_session.commit()
                    
                    res = await self._process_single_execution(
                        execution, parsed_signal, mt5_executor, user_prefs, credential_manager, manager
                    )
                    results.append(res)
                
                return {"success": True, "results": results}
            
        except Exception as e:
            logger.error(f"Critical error in signal execution: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "execution_id": None,
            }
    
    async def _process_single_execution(
        self,
        execution: Any, # TradeExecution object
        parsed_signal: Dict[str, Any],
        mt5_executor: Any,
        user_prefs: Any,
        credential_manager: Any,
        manager: Any, # WS manager
    ) -> Dict[str, Any]:
        """Process a single trade execution position."""
        execution_id = execution.id
        user_id = execution.user_id
        
        self.active_executions[execution_id] = {
            "signal_id": execution.signal_id,
            "status": execution.execution_status,
            "started_at": datetime.utcnow(),
        }
        
        try:
            # Validate signal
            if not self._validate_signal(parsed_signal):
                execution.execution_status = ExecutionState.FAILED.value
                execution.execution_error = "Signal validation failed"
                self.db_session.commit()
                return {"success": False, "error": "Signal validation failed", "execution_id": execution_id}
            
            execution.execution_status = ExecutionState.VALIDATED.value
            self.active_executions[execution_id]["status"] = ExecutionState.VALIDATED.value
            
            # Get credentials
            credentials = credential_manager.get_broker_credentials(self.db_session, user_id, execution.broker_config_id)
            if not credentials.get("mt5_password"):
                raise ValueError("MT5 password not configured")
            
            # Connect to MT5
            from models import BrokerConfig
            broker_config = self.db_session.query(BrokerConfig).filter(BrokerConfig.id == execution.broker_config_id).first()
            connection_result = await mt5_executor.connect(
                login=int(broker_config.login),
                password=credentials.get("mt5_password"),
                server=broker_config.server,
            )
            if not connection_result:
                raise RuntimeError("Failed to connect to MT5")
            
            # --- Entry Range & Limit Order Logic ---
            use_limit = False
            execution_price = float(execution.entry_price or 0)
            current_price = None
            
            price_info = mt5_executor.get_current_price(execution.symbol)
            if price_info:
                current_price = price_info["ask"] if execution.side == "buy" else price_info["bid"]
                
                # Check for Range logic
                entry_range = parsed_signal.get("entry_range", [])
                if entry_range and len(entry_range) == 2:
                    low, high = entry_range
                    if execution.side == "buy":
                        if current_price <= high:
                            # Within or below range, use market
                            use_limit = False
                        else:
                            # Above range, use limit order at the edge
                            use_limit = True
                            execution_price = high
                    else: # sell
                        if current_price >= low:
                            # Within or above range, use market
                            use_limit = False
                        else:
                            # Below range, use limit order at the edge
                            use_limit = True
                            execution_price = low
                
                # Fallback to slippage-based limit order if no range but user prefers limit
                elif user_prefs and user_prefs.use_limit_orders and execution.entry_price:
                    target_price = float(execution.entry_price)
                    point = price_info["point"]
                    price_diff = abs(current_price - target_price)
                    
                    if price_info["digits"] in [3, 5]:
                        pips_to_price = float(user_prefs.max_slippage) * 10 * point
                    else:
                        pips_to_price = float(user_prefs.max_slippage) * point
                    
                    if price_diff > pips_to_price:
                        use_limit = True
                        execution_price = target_price
            
            # Execute order
            execution.execution_status = ExecutionState.EXECUTING.value
            self.active_executions[execution_id]["status"] = ExecutionState.EXECUTING.value
            
            await manager.broadcast({
                "type": "execution_update",
                "execution_id": str(execution_id),
                "status": "executing",
                "symbol": execution.symbol
            }, user_id=user_id)
            
            order_result = None
            if use_limit:
                 logger.info(f"Executing LIMIT order: {execution.symbol} {execution.side} at {execution_price}")
                 order_result = await mt5_executor.execute_limit_order(
                    symbol=execution.symbol,
                    side=execution.side,
                    price=execution_price,
                    volume=float(execution.volume),
                    stop_loss=float(execution.stop_loss) if execution.stop_loss else None,
                    take_profit=float(execution.take_profit) if execution.take_profit else None,
                    comment=f"Signal {execution.signal_id}",
                )
            else:
                logger.info(f"Executing MARKET order: {execution.symbol} {execution.side}")
                order_result = await mt5_executor.execute_market_order(
                    symbol=execution.symbol,
                    side=execution.side,
                    volume=float(execution.volume),
                    stop_loss=float(execution.stop_loss) if execution.stop_loss else None,
                    take_profit=float(execution.take_profit) if execution.take_profit else None,
                    comment=f"Signal {execution.signal_id}",
                )
                
                # Market-to-Limit Fallback: If market order fails, try as a limit order
                if not order_result.get("success") and execution.entry_price:
                    logger.warning(f"Market order failed: {order_result.get('error')}. Falling back to LIMIT order at {execution.entry_price}")
                    
                    # Broadcast fallback notification
                    await manager.broadcast({
                        "type": "execution_update",
                        "execution_id": str(execution_id),
                        "status": "falling_back",
                        "message": f"Market order failed, placing limit order at {execution.entry_price}"
                    }, user_id=user_id)
                    
                    order_result = await mt5_executor.execute_limit_order(
                        symbol=execution.symbol,
                        side=execution.side,
                        price=float(execution.entry_price),
                        volume=float(execution.volume),
                        stop_loss=float(execution.stop_loss) if execution.stop_loss else None,
                        take_profit=float(execution.take_profit) if execution.take_profit else None,
                        comment=f"Signal {execution.signal_id} (Fallback)",
                    )
            
            if not order_result.get("success"):
                raise RuntimeError(order_result.get("error", "Order execution failed"))
            
            # Update execution record
            execution.execution_status = ExecutionState.EXECUTED.value
            execution.ticket_number = order_result.get("ticket")
            execution.order_id = str(order_result.get("order_id"))
            execution.actual_entry_price = order_result.get("entry_price")
            execution.actual_entry_time = datetime.utcnow()
            execution.executed_at = datetime.utcnow()
            self.db_session.commit()
            
            self.active_executions[execution_id]["status"] = ExecutionState.EXECUTED.value
            self.active_executions[execution_id]["ticket"] = order_result.get("ticket")
            
            await manager.broadcast({
                "type": "execution_update",
                "execution_id": str(execution_id),
                "status": "executed",
                "ticket": execution.ticket_number
            }, user_id=user_id)
            
            # Update signal status
            await self._update_signal_status(execution.signal_id)
            
            return {
                "success": True,
                "execution_id": execution_id,
                "ticket": execution.ticket_number,
                "entry_price": float(execution.actual_entry_price) if execution.actual_entry_price else None,
            }
            
        except Exception as e:
            logger.error(f"Error executing position: {e}", exc_info=True)
            execution.execution_status = ExecutionState.FAILED.value
            execution.execution_error = str(e)
            self.db_session.commit()
            
            # Update signal status
            await self._update_signal_status(execution.signal_id)
            
            try:
                await manager.broadcast({
                    "type": "error",
                    "execution_id": str(execution_id),
                    "message": str(e)
                }, user_id=user_id)
            except: pass
            
            return {"success": False, "error": str(e), "execution_id": execution_id}
    
    def _validate_signal(self, parsed_signal: Dict[str, Any]) -> bool:
        """Validate parsed signal for execution."""
        # Check required fields
        if not parsed_signal.get("symbol"):
            logger.warning("Signal missing symbol")
            return False
        
        if not parsed_signal.get("signal_type"):
            logger.warning("Signal missing signal_type")
            return False
        
        # Check confidence threshold
        if parsed_signal.get("confidence_score", 0) < 0.5:
            logger.warning(f"Low confidence signal: {parsed_signal.get('confidence_score')}")
            return False
        
        # Validate price consistency
        entry = parsed_signal.get("entry_price")
        sl = parsed_signal.get("stop_loss")
        tp = parsed_signal.get("take_profit")
        
        if entry and sl and tp:
            signal_type = parsed_signal.get("signal_type")
            
            if signal_type == "buy":
                if not (sl < entry < tp):
                    reason = f"Buy signal: invalid price levels (SL:{sl} should be below entry:{entry}, TP:{tp} above)"
                    logger.warning(reason)
                    return False
            elif signal_type == "sell":
                if not (tp < entry < sl):
                    reason = f"Sell signal: invalid price levels (TP:{tp} should be below entry:{entry}, SL:{sl} above)"
                    logger.warning(reason)
                    return False
        
        return True
    
    async def close_position(
        self,
        execution_id: UUID,
        mt5_executor,
        credential_manager,
        manager,
    ) -> Dict[str, Any]:
        """Close an open position."""
        try:
            from models import TradeExecution, BrokerConfig
            
            execution = self.db_session.query(TradeExecution).filter(
                TradeExecution.id == execution_id
            ).first()
            
            if not execution:
                return {"success": False, "error": "Execution not found"}
            
            if not execution.ticket_number:
                return {"success": False, "error": "No ticket number for position"}
            
            # Get credentials
            credentials = credential_manager.get_broker_credentials(
                self.db_session,
                execution.user_id,
                execution.broker_config_id,
            )
            
            broker_config = self.db_session.query(BrokerConfig).filter(
                BrokerConfig.id == execution.broker_config_id
            ).first()
            
            # Connect and close
            await mt5_executor.connect(
                login=int(broker_config.login),
                password=credentials.get("mt5_password"),
                server=broker_config.server,
            )
            
            close_result = await mt5_executor.close_position(
                symbol=execution.symbol,
                ticket=execution.ticket_number,
            )
            
            if not close_result.get("success"):
                return {"success": False, "error": close_result.get("error")}
            
            # Update execution
            execution.execution_status = ExecutionState.CLOSED.value
            execution.close_price = close_result.get("close_price")
            execution.close_time = datetime.utcnow()
            execution.profit_loss = close_result.get("profit_loss")
            
            self.db_session.commit()
            
            # Broadcast closure
            await manager.broadcast({
                "type": "position_closed",
                "execution_id": str(execution.id),
                "profit_loss": float(execution.profit_loss or 0),
                "close_price": float(execution.close_price or 0)
            }, user_id=execution.user_id)
            
            logger.info(f"Position closed: {execution_id}, P&L: {execution.profit_loss}")
            
            return {
                "success": True,
                "close_price": close_result.get("close_price"),
                "profit_loss": close_result.get("profit_loss"),
            }
            
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return {"success": False, "error": str(e)}
    
    async def reject_execution(self, execution_id: UUID) -> Dict[str, Any]:
        """Reject a pending execution."""
        try:
            from models import TradeExecution
            execution = self.db_session.query(TradeExecution).filter(
                TradeExecution.id == execution_id
            ).first()
            
            if not execution:
                return {"success": False, "error": "Execution not found"}
            
            if execution.execution_status != ExecutionState.PENDING_APPROVAL.value:
                return {"success": False, "error": "Only pending approvals can be rejected"}
            
            execution.execution_status = ExecutionState.CANCELLED.value
            self.db_session.commit()
            
            # Use helper to update signal status
            await self._update_signal_status(execution.signal_id)
            
            logger.info(f"Execution rejected: {execution_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error rejecting execution: {e}")
            return {"success": False, "error": str(e)}

    def get_execution_status(self, execution_id: UUID) -> Dict[str, Any]:
        """Get status of an execution."""
        try:
            from models import TradeExecution
            
            execution = self.db_session.query(TradeExecution).filter(
                TradeExecution.id == execution_id
            ).first()
            
            if not execution:
                return {"error": "Execution not found"}
            
            return {
                "execution_id": str(execution.id),
                "signal_id": str(execution.signal_id),
                "status": execution.execution_status,
                "ticket": execution.ticket_number,
                "symbol": execution.symbol,
                "side": execution.side,
                "volume": float(execution.volume),
                "entry_price": float(execution.entry_price) if execution.entry_price else None,
                "actual_entry_price": float(execution.actual_entry_price) if execution.actual_entry_price else None,
                "stop_loss": float(execution.stop_loss) if execution.stop_loss else None,
                "take_profit": float(execution.take_profit) if execution.take_profit else None,
                "profit_loss": float(execution.profit_loss) if execution.profit_loss else None,
                "executed_at": execution.executed_at.isoformat() if execution.executed_at else None,
                "closed_at": execution.close_time.isoformat() if execution.close_time else None,
                "error": execution.execution_error,
            }
        except Exception as e:
            logger.error(f"Error getting execution status: {e}")
            return {"error": str(e)}
    
    def get_user_executions(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get user's recent executions."""
        try:
            from models import TradeExecution
            
            executions = self.db_session.query(TradeExecution).filter(
                TradeExecution.user_id == user_id
            ).order_by(
                TradeExecution.created_at.desc()
            ).limit(limit).offset(offset).all()
            
            return [
                {
                    "execution_id": str(e.id),
                    "signal_id": str(e.signal_id),
                    "status": e.execution_status,
                    "symbol": e.symbol,
                    "side": e.side,
                    "ticket": e.ticket_number,
                    "profit_loss": float(e.profit_loss) if e.profit_loss else None,
                    "entry_price": float(e.entry_price) if e.entry_price else None,
                    "actual_entry_price": float(e.actual_entry_price) if e.actual_entry_price else None,
                    "stop_loss": float(e.stop_loss) if e.stop_loss else None,
                    "take_profit": float(e.take_profit) if e.take_profit else None,
                    "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                }
                for e in executions
            ]
        except Exception as e:
            logger.error(f"Error getting user executions: {e}")
            return []
    async def _update_signal_status(self, signal_id: UUID):
        """Check all executions for a signal and update signal status if all are resolved."""
        from models import Signal, TradeExecution
        signal = self.db_session.query(Signal).filter(Signal.id == signal_id).first()
        if not signal:
            return
            
        all_executions = self.db_session.query(TradeExecution).filter(
            TradeExecution.signal_id == signal_id
        ).all()
        
        if not all_executions:
            return
            
        resolved_states = [
            ExecutionState.CANCELLED.value,
            ExecutionState.FAILED.value,
            ExecutionState.EXECUTED.value,
            ExecutionState.CLOSED.value
        ]
        
        if all(ex.execution_status in resolved_states for ex in all_executions):
            # If all were cancelled, it's rejected. If at least one was executed, it's processed.
            if all(ex.execution_status == ExecutionState.CANCELLED.value for ex in all_executions):
                signal.status = "rejected"
            else:
                signal.status = "processed"
            signal.processed_at = datetime.utcnow()
            self.db_session.commit()
            
            from api.websockets import manager
            await manager.broadcast({
                "type": "signal_update",
                "signal_id": str(signal.id),
                "status": signal.status
            }, user_id=signal.user_id)


class AuditLogger:
    """Log all actions for audit trail."""
    
    @staticmethod
    def log_action(
        db_session: Session,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: Optional[UUID] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """Log an action."""
        try:
            from models import AuditLog
            
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            
            db_session.add(audit_log)
            db_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error logging action: {e}")
            return False
            
    @staticmethod
    def get_user_audit_logs(
        db_session: Session,
        user_id: UUID,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get user's audit logs."""
        try:
            from models import AuditLog
            
            logs = db_session.query(AuditLog).filter(
                AuditLog.user_id == user_id
            ).order_by(
                AuditLog.created_at.desc()
            ).limit(limit).all()
            
            return [
                {
                    "timestamp": log.created_at.isoformat(),
                    "action": log.action,
                    "resource_type": log.resource_type,
                    "details": log.details,
                }
                for log in logs
            ]
        except Exception as e:
            logger.error(f"Error getting audit logs: {e}")
            return []
