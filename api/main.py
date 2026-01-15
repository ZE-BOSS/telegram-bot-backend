"""Main FastAPI application."""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import asyncio
from datetime import datetime
from database import init_db
from api.routes import router
from api.auth_routes import router as auth_router
from config import load_config

logger = logging.getLogger(__name__)

config = load_config()

# System state for background listener
system_task = None
platform_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Setup Logging to WebSocket
    from api.websockets import WebSocketLogHandler, manager
    ws_handler = WebSocketLogHandler()
    ws_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    ws_handler.setFormatter(formatter)
    logging.getLogger().addHandler(ws_handler)
    logger.info("WebSocket Log Handler attached to API process")

    # Initialize DB
    logger.info("Initializing database...")
    init_db()
    
    # Start background ping task to keep WebSockets alive
    async def heartbeat_ping():
        while True:
            await asyncio.sleep(30)
            await manager.broadcast({"type": "ping", "timestamp": datetime.utcnow().isoformat()})
            
    ping_task = asyncio.create_task(heartbeat_ping())
    
    yield
    
    # Shutdown
    logger.info("Shutting down API system...")
    ping_task.cancel()
    
app = FastAPI(
    title="Trading Signal Automation Platform API",
    description="API for multi-user trading signal processing and execution",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(auth_router)
app.include_router(router)

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Trading Signal Automation Platform",
        "version": "1.0.0",
        "api": "/api",
        "docs": "/docs",
    }

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    from datetime import datetime
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Internal control endpoints for the UI to call
@app.post("/api/system/start")
async def start_system():
    global system_task, platform_instance
    if system_task and not system_task.done():
        return {"status": "running", "message": "Already running"}
    
    from main import TradingSignalPlatform
    platform_instance = TradingSignalPlatform()
    
    async def run_platform():
        try:
            await platform_instance.run()
        except Exception as e:
            logger.error(f"Platform error: {e}", exc_info=True)
            
    system_task = asyncio.create_task(run_platform())
    logger.info("Background Trading Listener started inside API process")
    return {"status": "running", "message": "System started"}

@app.post("/api/system/stop")
async def stop_system():
    global system_task, platform_instance
    if platform_instance:
        await platform_instance.shutdown()
        platform_instance = None
    
    if system_task:
        system_task.cancel()
        try:
            await system_task
        except asyncio.CancelledError:
            pass
        system_task = None
        
    logger.info("Background Trading Listener stopped")
    return {"status": "stopped", "message": "System stopped"}

@app.get("/api/system/status")
async def get_system_status():
    global system_task
    if system_task and not system_task.done():
        import os
        return {"status": "running", "pid": os.getpid()}
    return {"status": "stopped", "pid": None}

# WebSocket Endpoint
from fastapi import WebSocket, WebSocketDisconnect, Query
from api.websockets import manager
from api.auth_routes import get_current_user_from_token

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for real-time updates."""
    # Authenticate
    try:
        user = await get_current_user_from_token(token)
    except Exception as e:
        logger.error(f"WebSocket auth failed: {e}")
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user.id)
    try:
        while True:
            # Keep connection open and listen for client messages if needed
            # For now we only broadcast server -> client
            data = await websocket.receive_text()
            # Handle client messages if necessary (e.g. ping/pong)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user.id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, user.id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=config.debug,
    )
