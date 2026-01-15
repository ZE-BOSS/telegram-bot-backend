"""Main application entry point."""
import asyncio
import logging
import sys
from pathlib import Path

# Add backend and project root to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from core.telegram_listener import TelegramListener, TelegramSignalListener
from core.signal_parser import SignalParser
from core.mt5_executor import MT5Executor
from core.credential_manager import CredentialManager
from core.execution_state_manager import SignalExecutor
from core.sync_manager import PositionSyncManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('log')
    ]
)
logger = logging.getLogger(__name__)

class TradingSignalPlatform:
    """Main application orchestrator."""
    
    def __init__(self):
        """Initialize platform."""
        self.config = load_config()
        self.engine = None
        self.Session = None
        self.telegram_listener = None
        self.signal_listener = None
        self.signal_parser = None
        self.mt5_executor = None
        self.credential_manager = None
        self.sync_manager = None
    
    async def initialize(self):
        """Initialize all components."""
        logger.info("Initializing Trading Signal Platform...")
        
        try:
            # Initialize database
            self.engine = create_engine(
                self.config.database.url,
                pool_size=self.config.database.pool_size,
                max_overflow=self.config.database.max_overflow,
                echo=self.config.debug
            )
            
            # Create tables
            Base.metadata.create_all(self.engine)
            self.Session = sessionmaker(bind=self.engine)
            logger.info("Database initialized")
            
            # Initialize components
            self.telegram_listener = TelegramListener(
                api_id=self.config.telegram.api_id,
                api_hash=self.config.telegram.api_hash,
                phone=self.config.telegram.phone_number,
                session_name=self.config.telegram.session_name,
            )
            
            self.signal_parser = SignalParser(model=self.config.llm.model)
            self.credential_manager = CredentialManager()
            self.mt5_executor = MT5Executor(mt5_path=self.config.mt5.mt5_path)
            self.sync_manager = PositionSyncManager(self.Session)
            
            logger.info("All components initialized")
            
        except Exception as e:
            logger.error(f"Error initializing platform: {e}", exc_info=True)
            raise
    
    async def run(self):
        await self.initialize()

        if not await self.telegram_listener.connect():
            raise RuntimeError("Failed to connect to Telegram")

        db_session = self.Session()
        self.signal_listener = TelegramSignalListener(self.telegram_listener, db_session)
        self.signal_listener.signal_parser = self.signal_parser
        
        # Define execution wrapper
        async def execute_signal_wrapper(signal):
            """Bridge between listener and executing logic."""
            try:
                from models import BrokerConfig
                db = self.Session()
                try:
                    # Find all broker configs for the user
                    brokers = db.query(BrokerConfig).filter(
                        BrokerConfig.user_id == signal.user_id
                    ).all()
                    
                    if not brokers:
                        logger.warning(f"No broker configs found for user {signal.user_id}, skipping execution.")
                        return

                    executor = SignalExecutor(db)
                    
                    for broker in brokers:
                        logger.info(f"Executing signal {signal.id} for broker {broker.broker_name}")
                        await executor.execute_signal(
                            signal_id=signal.id,
                            broker_config_id=broker.id,
                            user_id=signal.user_id,
                            parsed_signal=signal.parsed_data or {},
                            mt5_executor=self.mt5_executor,
                            credential_manager=self.credential_manager,
                        )
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error in execution wrapper: {e}", exc_info=True)

        self.signal_listener.execution_handler = execute_signal_wrapper
        
        # Pass necessary config for forwarding
        self.signal_listener.forward_to_id = self.config.telegram.phone_number # Using self phone as default if not separate, or lookup
        # Actually, let's assume we want to forward to "Saved Messages" ("me") or a specific ID if in config?
        # The user request said "personalised user telegram account".
        # Since TelegramConfig only has phone, let's try to forward to "me" (Saved Messages) as a fallback verify
        # OR we can just inject the whole config or listener


        # 🔥 REGISTER CHANNELS FIRST
        from models import TelegramChannel
        channels = db_session.query(TelegramChannel).filter(
            TelegramChannel.is_active == True
        ).all()

        for channel in channels:
            await self.telegram_listener.register_channel(
                channel.channel_id,
                channel.user_id,
                self.signal_listener.handle_signal_message,
            )

        # 🔥 THEN start listening
        logger.info(f"Listener started. Monitoring {len(channels)} channels.")
        
        # Start heartbeat loop in background
        async def heartbeat():
             while True:
                 logger.info("[HEARTBEAT] System Heartbeat - Listener Active")
                 await asyncio.sleep(60) # Log every minute
        
        asyncio.create_task(heartbeat())
        
        # Start position sync
        await self.sync_manager.start()
        
        await self.telegram_listener.start_listening()

    async def shutdown(self):
        """Shutdown platform."""
        logger.info("Shutting down...")
        
        if self.telegram_listener:
            await self.telegram_listener.disconnect()
        
        if self.sync_manager:
            await self.sync_manager.stop()
            
        if self.mt5_executor:
            self.mt5_executor.disconnect()
        
        if self.engine:
            self.engine.dispose()
        
        logger.info("Shutdown complete")


async def main():
    """Entry point."""
    platform = TradingSignalPlatform()
    await platform.run()


if __name__ == "__main__":
    asyncio.run(main())
