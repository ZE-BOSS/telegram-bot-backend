"""Database initialization and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from models import Base
from config import load_config
import logging
import os

logger = logging.getLogger(__name__)

config = load_config()

# Create engine
engine = create_engine(
    config.database.url,
    pool_size=config.database.pool_size,
    max_overflow=config.database.max_overflow,
    echo=config.debug,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
