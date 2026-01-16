"""MT5 trade execution engine."""
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)

class MT5Executor:
    """Execute trades on MT5 platform."""
    
    def __init__(self, mt5_path: Optional[str] = None, timeout: int = 30):
        """Initialize MT5 executor."""
        self.mt5_path = mt5_path
        self.mt5 = None
        self.is_connected = False
        self.timeout = timeout
        self.active_connections: Dict[str, Any] = {}
    
    async def connect(self, login: int, password: str, server: str) -> bool:
        """Connect to MT5 account."""
        try:
            import MetaTrader5 as mt5
            
            # Initialize MT5 if not already done
            init_params = {
                "login": login,
                "password": password,
                "server": server
            }
            if self.mt5_path:
                init_params["path"] = self.mt5_path
                
            if not mt5.initialize(**init_params):
                logger.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False
            
            # Connect to account
            if not mt5.login(login, password=password, server=server):
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False
            
            self.mt5 = mt5
            self.is_connected = True
            connection_key = f"{login}_{server}"
            self.active_connections[connection_key] = {
                "login": login,
                "server": server,
                "connected_at": datetime.utcnow(),
            }
            
            logger.info(f"Connected to MT5 account {login} on {server}")
            return True
        except ImportError:
            logger.error("MetaTrader5 library not installed")
            return False
        except Exception as e:
            logger.error(f"Error connecting to MT5: {e}", exc_info=True)
            return False
    
    async def execute_market_order(
        self,
        symbol: str,
        side: str,  # 'buy' or 'sell'
        volume: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        comment: str = "Trading Signal",
    ) -> Dict[str, Any]:
        """Execute a market order on MT5."""
        if not self.is_connected or not self.mt5:
            return {
                "success": False,
                "error": "Not connected to MT5",
                "ticket": None
            }
        
        try:
            # Validate inputs
            if side.lower() not in ["buy", "sell"]:
                return {"success": False, "error": "Invalid side (must be 'buy' or 'sell')"}
            
            # Get order type
            order_type = self.mt5.ORDER_TYPE_BUY if side.lower() == "buy" else self.mt5.ORDER_TYPE_SELL
            
            # Get current price for reference
            symbol_info = self.mt5.symbol_info(symbol)
            if not symbol_info:
                return {"success": False, "error": f"Symbol {symbol} not found"}
            
            # Use ask price for buys, bid for sells
            current_price = symbol_info.ask if side.lower() == "buy" else symbol_info.bid
            
            # Determine filling type
            # SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2
            filling_mode = getattr(symbol_info, 'filling_mode', 0)
            if filling_mode & 1:
                filling_type = self.mt5.ORDER_FILLING_FOK
            elif filling_mode & 2:
                filling_type = self.mt5.ORDER_FILLING_IOC
            else:
                filling_type = self.mt5.ORDER_FILLING_RETURN

            # Create order request
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "comment": comment,
                "type_filling": filling_type,
            }
            
            # Only add SL/TP if they are set (some brokers reject 0 values)
            if stop_loss:
                request["sl"] = float(stop_loss)
            if take_profit:
                request["tp"] = float(take_profit)
            
            logger.info(f"Executing {side} order: {volume} {symbol} @ {current_price} (Filling: {filling_type})")
            logger.debug(f"Full MT5 Request: {request}")
            
            # Send order
            result = self.mt5.order_send(request)
            
            if result is None:
                error_msg = f"Order send failed (result is None). Last error: {self.mt5.last_error()}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "ticket": None}

            if result.retcode != self.mt5.TRADE_RETCODE_DONE:
                logger.error(f"Order execution failed: {result.comment} (code: {result.retcode})")
                return {
                    "success": False,
                    "error": result.comment or f"Error code {result.retcode}",
                    "ticket": None,
                    "retcode": result.retcode
                }
            
            logger.info(f"Order executed: Ticket {result.order}")
            return {
                "success": True,
                "ticket": result.order,
                "order_id": str(result.order),
                "volume": float(volume),
                "symbol": symbol,
                "side": side,
                "entry_price": float(current_price),
                "stop_loss": float(stop_loss) if stop_loss else None,
                "take_profit": float(take_profit) if take_profit else None,
                "executed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error executing order: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "ticket": None
            }

    async def execute_limit_order(
        self,
        symbol: str,
        side: str,  # 'buy' or 'sell'
        price: float,
        volume: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        comment: str = "Limit Order",
        expiration: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Execute a limit order on MT5."""
        if not self.is_connected or not self.mt5:
            return {"success": False, "error": "Not connected to MT5"}
        
        try:
            # Validate inputs
            if side.lower() not in ["buy", "sell"]:
                return {"success": False, "error": "Invalid side"}

            # Limit Buy = Below current price
            # Limit Sell = Above current price
            # Stop Buy = Above current price
            # Stop Sell = Below current price
            # For simplicity, we assume generic 'limit' meaning 'get a better price'
            # But technically:
            # - Buy Limit: Ask < Price (buying below market)
            # - Sell Limit: Bid > Price (selling above market)
            
            order_type = self.mt5.ORDER_TYPE_BUY_LIMIT if side.lower() == "buy" else self.mt5.ORDER_TYPE_SELL_LIMIT
            
            request = {
                "action": self.mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": float(price),
                "comment": comment,
                "type_filling": self.mt5.ORDER_FILLING_RETURN,
            }
            
            # Only add SL/TP if they are set
            if stop_loss:
                request["sl"] = float(stop_loss)
            if take_profit:
                request["tp"] = float(take_profit)
            
            if expiration:
                request["type_time"] = self.mt5.ORDER_TIME_SPECIFIED
                request["expiration"] = int(expiration.timestamp())

            logger.info(f"Placing {side} LIMIT order: {volume} {symbol} @ {price}")
            
            result = self.mt5.order_send(request)
            
            if result is None:
                error_msg = f"Limit order failed (result is None). Last error: {self.mt5.last_error()}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "retcode": None}

            if result.retcode != self.mt5.TRADE_RETCODE_DONE:
                logger.error(f"Limit order failed: {result.comment} (code: {result.retcode})")
                return {
                    "success": False, 
                    "error": result.comment or f"Error code {result.retcode}",
                    "retcode": result.retcode
                }

            logger.info(f"Limit order placed: Ticket {result.order}")
            return {
                "success": True,
                "ticket": result.order,
                "order_id": str(result.order),
                "volume": float(volume),
                "price": float(price),
                "placed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error placing limit order: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def close_position(self, symbol: str, ticket: int) -> Dict[str, Any]:
        """Close an open position."""
        if not self.is_connected or not self.mt5:
            return {"success": False, "error": "Not connected to MT5"}
        
        try:
            # Get position info
            position = self.mt5.positions_get(ticket=ticket)
            if not position:
                return {"success": False, "error": f"Position {ticket} not found"}
            
            pos = position[0]
            
            # Determine opposite order type
            close_type = self.mt5.ORDER_TYPE_SELL if pos.type == 0 else self.mt5.ORDER_TYPE_BUY
            
            # Get current price
            symbol_info = self.mt5.symbol_info(symbol)
            if not symbol_info:
                return {"success": False, "error": f"Symbol {symbol} not found"}
            
            current_price = symbol_info.bid if pos.type == 0 else symbol_info.ask
            
            # Create close order
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": close_type,
                "position": ticket,
                "price": float(current_price),
                "comment": "Position closed by Trading Signal Bot",
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
            
            result = self.mt5.order_send(request)
            
            if result is None:
                return {"success": False, "error": "Order send failed, no result from MT5"}

            if result.retcode != self.mt5.TRADE_RETCODE_DONE:
                return {"success": False, "error": f"Close failed: {result.comment} (code: {result.retcode})", "retcode": result.retcode}
            
            # Use the actual price from the deal if available
            actual_price = result.price if hasattr(result, 'price') and result.price > 0 else current_price
            profit_loss = result.profit if hasattr(result, 'profit') else None
            
            logger.info(f"Position closed: Ticket {ticket}, P&L: {profit_loss}")
            return {
                "success": True,
                "closing_ticket": result.order,
                "close_price": float(actual_price),
                "profit_loss": float(profit_loss) if profit_loss else None,
                "closed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return {"success": False, "error": str(e)}
    
    async def modify_position(
        self,
        ticket: int,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Modify stop loss and/or take profit of a position."""
        if not self.is_connected or not self.mt5:
            return {"success": False, "error": "Not connected to MT5"}
        
        try:
            position = self.mt5.positions_get(ticket=ticket)
            if not position:
                return {"success": False, "error": f"Position {ticket} not found"}
            
            pos = position[0]
            
            # Create modify request
            request = {
                "action": self.mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": float(stop_loss) if stop_loss else pos.sl,
                "tp": float(take_profit) if take_profit else pos.tp,
            }
            
            result = self.mt5.order_send(request)
            
            if result.retcode != self.mt5.TRADE_RETCODE_DONE:
                return {"success": False, "error": result.comment}
            
            logger.info(f"Position modified: Ticket {ticket}")
            return {
                "success": True,
                "ticket": ticket,
                "new_sl": float(stop_loss) if stop_loss else None,
                "new_tp": float(take_profit) if take_profit else None,
                "modified_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error modifying position: {e}")
            return {"success": False, "error": str(e)}
    
    def get_current_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current market price and symbol info for a symbol."""
        if not self.is_connected or not self.mt5:
            return None
            
        try:
            # Get symbol info
            symbol_info = self.mt5.symbol_info(symbol)
            if not symbol_info:
                return None
            
            # Get latest tick
            tick = self.mt5.symbol_info_tick(symbol)
            if not tick:
                return None
                
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "point": symbol_info.point,
                "digits": symbol_info.digits,
                "spread": symbol_info.spread,
                "trade_mode": symbol_info.trade_mode
            }
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def get_account_info(self) -> Dict[str, Any]:
        """Get MT5 account information."""
        if not self.is_connected or not self.mt5:
            return {"error": "Not connected to MT5"}
        
        try:
            account_info = self.mt5.account_info()
            return {
                "login": account_info.login,
                "server": account_info.server,
                "balance": float(account_info.balance),
                "equity": float(account_info.equity),
                "profit": float(account_info.profit),
                "margin": float(account_info.margin),
                "margin_free": float(account_info.margin_free),
                "margin_level": float(account_info.margin_level) if account_info.margin_level > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {"error": str(e)}

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open positions."""
        if not self.is_connected or not self.mt5:
            return []
            
        try:
            positions = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
            if positions is None:
                return []
                
            result = []
            for p in positions:
                result.append({
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "volume": p.volume,
                    "type": p.type,  # 0=Buy, 1=Sell
                    "price_open": p.price_open,
                    "price_current": p.price_current,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit": p.profit,
                    "comment": p.comment,
                    "identifier": p.identifier,
                })
            return result
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_history_deals(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Get deal information for a closed position's ticket."""
        if not self.is_connected or not self.mt5:
            return None
            
        try:
            # history_deals_get(position=ticket) returns all deals associated with this position
            deals = self.mt5.history_deals_get(position=ticket)
            if not deals or len(deals) == 0:
                return None
            
            # Find the closing deal (usually the last one for that position)
            # For simplicity, we just look for a deal with non-zero profit if it was a closure
            closing_deal = None
            for d in reversed(deals):
                if d.entry == self.mt5.DEAL_ENTRY_OUT: # Closing deal
                    closing_deal = d
                    break
            
            if not closing_deal:
                closing_deal = deals[-1]

            return {
                "ticket": closing_deal.ticket,
                "order": closing_deal.order,
                "symbol": closing_deal.symbol,
                "volume": closing_deal.volume,
                "price": closing_deal.price,
                "profit": closing_deal.profit,
                "commission": closing_deal.commission,
                "swap": closing_deal.swap,
                "comment": closing_deal.comment,
                "time": datetime.fromtimestamp(closing_deal.time).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error getting history deals: {e}")
            return None
    
    def disconnect(self):
        """Disconnect from MT5."""
        if self.mt5:
            self.mt5.shutdown()
            self.is_connected = False
            self.active_connections.clear()
            logger.info("Disconnected from MT5")
