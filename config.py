"""Configuration management for the trading signal platform."""
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str
    pool_size: int = 10
    max_overflow: int = 20

@dataclass
class TelegramConfig:
    """Telegram API configuration."""
    api_id: int
    api_hash: str
    phone_number: str
    session_name: str = "trading_bot"

@dataclass
class MT5Config:
    """MT5 trading configuration."""
    mt5_path: Optional[str] = None
    timeout: int = 30

@dataclass
class LLMConfig:
    """LLM configuration for signal parsing."""
    model: str = "gpt-4"
    temperature: float = 0.3
    max_tokens: int = 500

@dataclass
class AppConfig:
    """Main application configuration."""
    database: DatabaseConfig
    telegram: TelegramConfig
    mt5: MT5Config
    llm: LLMConfig
    log_level: str = "INFO"
    debug: bool = False

def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    
    return AppConfig(
        database=DatabaseConfig(
            url=database_url
        ),
        telegram=TelegramConfig(
            api_id=int(os.getenv("TELEGRAM_API_ID")),
            api_hash=os.getenv("TELEGRAM_API_HASH"),
            phone_number=os.getenv("TELEGRAM_PHONE"),
        ),
        mt5=MT5Config(
            mt5_path=os.getenv("MT5_PATH"),
        ),
        llm=LLMConfig(
            model=os.getenv("LLM_MODEL", "gpt-4"),
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )
