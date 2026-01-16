"""Telegram message listener using Telethon."""
import asyncio
import logging
from typing import Callable, Optional, List, Dict, Any
from telethon import TelegramClient, events
from telethon.events import NewMessage
from telethon.errors import SessionPasswordNeededError
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from core.signal_parser import MessageCategory
from api.websockets import manager

logger = logging.getLogger(__name__)

class TelegramListener:
    """Listens to Telegram channels for trading signals."""
    
    def __init__(self, api_id: int, api_hash: str, phone: str, session_name: str):
        """Initialize Telegram client."""
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self.handlers: Dict[int, Callable] = {}  # track multiple channel handlers
        self.is_running = False
    
    async def connect(self):
        """Connect to Telegram with authentication via WebSocket."""
        try:
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.start(phone=self.phone)
            
            if not await self.client.is_user_authorized():
                await self.client.send_code_request(self.phone)
                
                # Broadcast code request to frontend and wait
                code = await self._get_user_input("get_code", self.phone)
                try:
                    await self.client.sign_in(self.phone, code)
                except SessionPasswordNeededError:
                    password = await self._get_user_input("get_password", self.phone)
                    await self.client.sign_in(password=password)
            
            self.is_running = True
            logger.info(f"Connected to Telegram as {self.phone}")
            return True
        except Exception as e:
            logger.error(f"Error connecting to Telegram: {e}", exc_info=True)
            return False
    
    async def _get_user_input(self, input_type: str, user_id: UUID = None) -> str:
        """
        Send an input request to the frontend and wait for a response.
        input_type: "get_code" or "get_password"
        """
        fut = asyncio.get_event_loop().create_future()
        
        # Broadcast the input request
        await manager.broadcast({
            "type": input_type,
            "requires_input": True,
            "message": f"Enter {input_type.replace('_', ' ')}"
        })
        
        value = await fut
        return value

    async def disconnect(self):
        """Disconnect from Telegram."""
        if self.client:
            await self.client.disconnect()
            self.is_running = False
            logger.info("Disconnected from Telegram")
    
    async def register_channel(
        self,
        channel_id: int,
        user_id: UUID,
        handler: Callable[[Dict[str, Any]], Any],
    ) -> bool:
        if not self.client or not self.is_running:
            logger.error("Telegram client not connected")
            return False

        try:
            try:
                entity = await self.client.get_entity(channel_id)
            except ValueError:
                # If entity not found, try refreshing dialogs
                logger.warning(f"Entity {channel_id} not found in cache, refreshing dialogs...")
                await self.client.get_dialogs()
                try:
                    entity = await self.client.get_entity(channel_id)
                except ValueError as e:
                    logger.error(f"Could not find entity for channel {channel_id} even after refresh: {e}")
                    return False

            logger.info(f"Resolved entity for channel {channel_id}: {entity.title} (ID: {entity.id})")

            async def on_new_message(event):
                logger.info(f"New message from {entity.title}")

                message_data = {
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "message_text": event.message.text or "",
                    "message_id": event.message.id,
                    "timestamp": event.message.date,
                    "from_user": event.message.from_id,
                    "media": event.message.media is not None,
                }

                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(message_data)
                    else:
                        handler(message_data)
                except Exception as handler_error:
                    logger.error(f"Error in signal handler: {handler_error}", exc_info=True)

            self.client.add_event_handler(
                on_new_message,
                events.NewMessage(chats=entity),
            )

            logger.info(f"Listening to channel: {entity.title} ({channel_id})")
            return True

        except Exception as e:
            logger.error(f"Failed to register channel {channel_id}: {e}", exc_info=True)
            return False

    async def start_listening(self):
        if not self.client:
            raise RuntimeError("Telegram client not connected")

        logger.info("Telegram listener running...")
        await self.client.run_until_disconnected()

    async def get_channel_info(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get information about a channel."""
        if not self.client or not self.is_running:
            return None
        
        try:
            entity = await self.client.get_entity(channel_id)
            return {
                "id": entity.id,
                "title": entity.title,
                "username": getattr(entity, 'username', None),
                "is_channel": hasattr(entity, 'broadcast') and entity.broadcast,
            }
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return None


class TelegramSignalListener:
    """Higher-level interface for listening to trading signals."""
    
    def __init__(self, listener: TelegramListener, db_session: Session):
        """Initialize signal listener."""
        self.listener = listener
        self.db_session = db_session
        self.signal_parser = None  # Injected from main app
        self.execution_handler = None  # Injected from main app
        self.forward_to_id: Optional[str] = "me"  # Default to "Saved Messages"

    async def handle_signal_message(self, message_data: Dict[str, Any]):
        """Process an incoming signal message."""
        try:
            logger.info(f"Processing signal message from channel {message_data['channel_id']}")
            
            # Parse the signal
            if not self.signal_parser:
                logger.error("Signal parser not configured")
                return
            
            parsed_signal = self.signal_parser.parse_signal(message_data["message_text"])

            if parsed_signal.get("message_category") != MessageCategory.ACTIONABLE_SIGNAL.value:
                logger.info(
                    f"Ignored non-actionable message "
                    f"[{parsed_signal.get('message_category')}] → {message_data['message_text'][:80]}"
                )
                await manager.broadcast({
                    "type": "telegram_message",
                    "category": parsed_signal.get("message_category"),
                    "channel_id": str(message_data["channel_id"]),
                    "message_id": message_data["message_id"],
                    "text": message_data["message_text"],
                    "timestamp": message_data["timestamp"].isoformat() if message_data["timestamp"] else None
                }, user_id=message_data["user_id"])
                return
            
            # Forwarding Logic (Now with reformatted data)
            try:
                from models import NotificationSubscriber
                
                subscribers = self.db_session.query(NotificationSubscriber).filter(
                    NotificationSubscriber.user_id == message_data["user_id"],
                    NotificationSubscriber.is_active == True
                ).all()

                if subscribers and self.listener.client:
                    symbol = parsed_signal.get("symbol", "UNKNOWN")
                    stype = (parsed_signal.get("signal_type") or "SIGNAL").upper()
                    
                    # Handle Entry display (Check range first)
                    entry_range = parsed_signal.get("entry_range", [])
                    if entry_range and len(entry_range) == 2:
                        entry_text = f"{entry_range[0]} - {entry_range[1]}"
                    else:
                        entry_text = str(parsed_signal.get("entry_price") or "Market")
                        
                    # Handle multiple TPs display
                    tps = parsed_signal.get("take_profits", [])
                    if not tps and parsed_signal.get("take_profit"):
                        tps = [parsed_signal.get("take_profit")]
                    
                    tp_text = "\n".join([f"🔹 **TP{i+1}:** {tp}" for i, tp in enumerate(tps)]) if tps else f"🔹 **TP:** {parsed_signal.get('take_profit') or '-'}"
                    
                    forward_text = (
                        f"🔔 **{stype}: {symbol}**\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🔹 **Entry:** {entry_text}\n"
                        f"🔹 **SL:** {parsed_signal.get('stop_loss') or '-'}\n"
                        f"{tp_text}\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"📊 **Analysis:**_{parsed_signal.get('raw_data', {}).get('llm_reasoning', 'No extra details')}_"
                    )
                    
                    for sub in subscribers:
                        try:
                            target = int(sub.telegram_id) if sub.telegram_id.lstrip('-').isdigit() else sub.telegram_id
                            await self.listener.client.send_message(target, forward_text)
                            logger.info(f"Forwarded reformatted signal to {sub.name}")
                        except Exception as fw_err:
                            logger.error(f"Failed to forward: {fw_err}")
                
            except Exception as fw_main_err:
                 logger.error(f"Error in forwarding logic: {fw_main_err}")

            # Create signal record in database
            from models import Signal, TelegramChannel
            
            telegram_channel = self.db_session.query(TelegramChannel).filter(
                TelegramChannel.channel_id == message_data["channel_id"],
                TelegramChannel.user_id == message_data["user_id"]
            ).first()
            
            if not telegram_channel:
                logger.error(f"Channel not found in database: {message_data['channel_id']}")
                return
            
            signal = Signal(
                user_id=message_data["user_id"],
                telegram_channel_id=telegram_channel.id,
                raw_message=message_data["message_text"],
                parsed_data=parsed_signal,
                signal_type=parsed_signal.get("signal_type"),
                symbol=parsed_signal.get("symbol"),
                entry_price=parsed_signal.get("entry_price"),
                stop_loss=parsed_signal.get("stop_loss"),
                take_profit=parsed_signal.get("take_profit"),
                confidence_score=parsed_signal.get("confidence_score"),
            )
            
            self.db_session.add(signal)
            self.db_session.commit()
            
            logger.info(f"Signal recorded: {signal.id}")
            
            # Broadcast WS event for live update
            await manager.broadcast({
                "type": "signal_received",
                "signal": {
                    "id": str(signal.id),
                    "symbol": signal.symbol,
                    "signal_type": signal.signal_type,
                    "entry_price": float(signal.entry_price) if signal.entry_price else None,
                    "stop_loss": float(signal.stop_loss) if signal.stop_loss else None,
                    "take_profit": float(signal.take_profit) if signal.take_profit else None,
                    "processed_at": None
                }
            }, user_id=message_data["user_id"])
            
            # Execute if handler is configured
            if self.execution_handler:
                await self.execution_handler(signal)
                
        except Exception as e:
            logger.error(f"Error handling signal message: {e}", exc_info=True)
            self.db_session.rollback()
