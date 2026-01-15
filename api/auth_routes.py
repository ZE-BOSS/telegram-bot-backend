"""Authentication routes."""
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from uuid import UUID
import bcrypt
import jwt
import os

from database import get_db
from models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

class LoginRequest(BaseModel):
    """Login request."""
    email: str
    password: str

class RegisterRequest(BaseModel):
    """Register request."""
    email: EmailStr
    password: str
    username: str

class AuthResponse(BaseModel):
    """Authentication response."""
    access_token: str
    user_id: str
    email: str
    username: str
    token_type: str = "bearer"

def hash_password(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hash_value: str) -> bool:
    """Verify a password."""
    return bcrypt.checkpw(password.encode(), hash_value.encode())

def create_access_token(data: dict) -> str:
    """Create JWT token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    try:
        # Check if user exists
        existing_user = db.query(User).filter(
            (User.email == request.email) | (User.username == request.username)
        ).first()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Create new user
        user = User(
            email=request.email,
            username=request.username,
            password_hash=hash_password(request.password),
            is_active=True,
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create token
        access_token = create_access_token({"sub": str(user.id), "email": user.email})
        
        logger.info(f"User registered: {user.email}")
        
        return AuthResponse(
            access_token=access_token,
            user_id=str(user.id),
            email=user.email,
            username=user.username,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login user."""
    try:
        user = db.query(User).filter(User.email == request.email).first()
        
        if not user or not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not user.is_active:
            raise HTTPException(status_code=401, detail="User is inactive")
        
        # Create token
        access_token = create_access_token({"sub": str(user.id), "email": user.email})
        
        logger.info(f"User logged in: {user.email}")
        
        return AuthResponse(
            access_token=access_token,
            user_id=str(user.id),
            email=user.email,
            username=user.username,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def get_current_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
) -> UUID:
    """Get current user from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.replace("Bearer ", "")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        return UUID(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user_from_token(token: str) -> User:
    """Get current user from token string (for WebSockets)."""
    from database import SessionLocal
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise Exception("Invalid token")
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == UUID(user_id)).first()
            if not user:
                raise Exception("User not found")
            return user
        finally:
            db.close()
            
    except Exception as e:
        raise Exception(f"Auth failed: {e}")
