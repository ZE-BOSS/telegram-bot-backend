from typing import List, Dict, Any
import json
import logging
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from uuid import UUID

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        # Map user_id to list of active websockets
        self.active_connections: Dict[UUID, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: UUID):
        """Accept connection and store user mapping."""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected: User {user_id}")
    
    def disconnect(self, websocket: WebSocket, user_id: UUID):
        """Remove connection."""
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                
        logger.info(f"WebSocket disconnected: User {user_id}")
    
    async def broadcast(self, message: Dict[str, Any], user_id: UUID = None):
        """Broadcast message to all or specific user."""
        json_message = json.dumps(message, default=str)
        
        if user_id:
            # Send to specific user
            if user_id in self.active_connections:
                for connection in self.active_connections[user_id]:
                    try:
                        await connection.send_text(json_message)
                    except Exception as e:
                        logger.error(f"Error sending WS message: {e}")
        else:
            # Broadcast to all (admin / system events)
            for user_connections in self.active_connections.values():
                for connection in user_connections:
                    try:
                        await connection.send_text(json_message)
                    except Exception as e:
                        logger.error(f"Error broadcasting WS message: {e}")

# Global instance
manager = ConnectionManager()

class WebSocketLogHandler(logging.Handler):
    """Custom logging handler to broadcast logs via WebSocket."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop = None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    def emit(self, record):
        try:
            log_entry = self.format(record)
            
            # Determine type based on level
            msg_type = "info"
            if record.levelno >= logging.ERROR:
                msg_type = "error"
            elif record.levelno >= logging.WARNING:
                msg_type = "warning"
                
            # Prepare message
            message = {
                "type": "log",
                "level": msg_type,
                "message": log_entry,
                "timestamp": record.created
            }
            
            # Broadcast
            try:
                # Try to get the current loop or use the one we found at init
                loop = self._loop
                try:
                    current_loop = asyncio.get_running_loop()
                    if current_loop:
                        loop = current_loop
                except RuntimeError:
                    pass
                
                if loop and loop.is_running():
                    # Thread-safe way to schedule a coroutine in the loop
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast(message),
                        loop
                    )
            except Exception:
                # Fallback if loop logic fails
                pass
                
        except Exception:
            self.handleError(record)
